"""Kraken public full-catalog discovery for AETHER vNext."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from aether_vnext.provider_discovery import DiscoveryInstrument


KRAKEN_REST_BASE = "https://api.kraken.com"
ASSET_PAIRS_PATH = "/0/public/AssetPairs"
TICKER_PATH = "/0/public/Ticker"
USD_QUOTES = {"USD", "ZUSD"}


def _num(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def parse_kraken_usd_catalog(payload: object) -> dict[str, dict[str, object]]:
    if not isinstance(payload, Mapping):
        raise ValueError("Kraken AssetPairs payload must be an object")
    errors = payload.get("error")
    if isinstance(errors, list) and errors:
        raise RuntimeError("kraken_asset_pairs:" + ",".join(str(x) for x in errors))
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("Kraken AssetPairs result missing")

    out: dict[str, dict[str, object]] = {}
    for pair_key, raw in result.items():
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("status") or "online").lower() != "online":
            continue
        quote = str(raw.get("quote") or "").upper()
        wsname = str(raw.get("wsname") or "").strip()
        altname = str(raw.get("altname") or pair_key).strip()
        if quote not in USD_QUOTES and not wsname.endswith("/USD"):
            continue
        if not wsname or ".d" in str(pair_key).lower():
            continue
        out[str(pair_key)] = {
            "pair_key": str(pair_key),
            "symbol": wsname,
            "altname": altname,
            "base": str(raw.get("base") or ""),
            "quote": quote,
            "ordermin": raw.get("ordermin"),
            "costmin": raw.get("costmin"),
            "pair_decimals": raw.get("pair_decimals"),
            "lot_decimals": raw.get("lot_decimals"),
        }
    return out


def parse_kraken_tickers(
    catalog: Mapping[str, Mapping[str, object]],
    payloads: list[object],
    *,
    observed_at_utc: datetime,
) -> tuple[DiscoveryInstrument, ...]:
    ticker_rows: dict[str, Mapping[str, object]] = {}
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise RuntimeError("kraken_ticker:" + ",".join(str(x) for x in errors))
        result = payload.get("result")
        if isinstance(result, Mapping):
            ticker_rows.update({
                str(key): value
                for key, value in result.items()
                if isinstance(value, Mapping)
            })

    out: list[DiscoveryInstrument] = []
    for pair_key, meta in catalog.items():
        raw = ticker_rows.get(pair_key)
        if raw is None:
            altname = str(meta.get("altname") or "")
            raw = ticker_rows.get(altname)
        if raw is None:
            continue
        last_arr = raw.get("c")
        open_raw = raw.get("o")
        high_arr = raw.get("h")
        low_arr = raw.get("l")
        volume_arr = raw.get("v")
        bid_arr = raw.get("b")
        ask_arr = raw.get("a")
        last = _num(last_arr[0] if isinstance(last_arr, list) and last_arr else None)
        open_price = _num(open_raw)
        high = _num(high_arr[-1] if isinstance(high_arr, list) and high_arr else None)
        low = _num(low_arr[-1] if isinstance(low_arr, list) and low_arr else None)
        volume = _num(volume_arr[-1] if isinstance(volume_arr, list) and volume_arr else None)
        bid = _num(bid_arr[0] if isinstance(bid_arr, list) and bid_arr else None)
        ask = _num(ask_arr[0] if isinstance(ask_arr, list) and ask_arr else None)
        change = (
            None
            if last is None or open_price is None or open_price <= 0
            else ((last - open_price) / open_price) * 100.0
        )
        out.append(
            DiscoveryInstrument(
                provider="Kraken",
                symbol=str(meta["symbol"]),
                market_data_symbol=str(meta["symbol"]),
                execution_symbol=str(meta["altname"]),
                asset_class="spot_crypto",
                active=True,
                price=last,
                open_price=open_price,
                high_price=high,
                low_price=low,
                volume=volume,
                bid=bid,
                ask=ask,
                change_pct=change,
                observed_at_utc=observed_at_utc,
                source="kraken_public_rest",
            )
        )
    return tuple(out)


async def fetch_kraken_discovery_universe(
    *,
    client: httpx.AsyncClient | None = None,
    ticker_chunk_size: int = 40,
) -> tuple[DiscoveryInstrument, ...]:
    if ticker_chunk_size <= 0:
        raise ValueError("ticker_chunk_size must be positive")
    owned = client is None
    http = client or httpx.AsyncClient(
        base_url=KRAKEN_REST_BASE,
        timeout=httpx.Timeout(15.0),
    )
    try:
        response = await http.get(ASSET_PAIRS_PATH)
        response.raise_for_status()
        catalog = parse_kraken_usd_catalog(response.json())
        keys = tuple(catalog)
        payloads: list[object] = []
        for start in range(0, len(keys), ticker_chunk_size):
            chunk = keys[start:start + ticker_chunk_size]
            ticker = await http.get(TICKER_PATH, params={"pair": ",".join(chunk)})
            ticker.raise_for_status()
            payloads.append(ticker.json())
            if start + ticker_chunk_size < len(keys):
                await asyncio.sleep(0)
        return parse_kraken_tickers(
            catalog,
            payloads,
            observed_at_utc=datetime.now(timezone.utc),
        )
    finally:
        if owned:
            await http.aclose()
