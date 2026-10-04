"""Kraken public full-catalog discovery for AETHER vNext."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Mapping

import httpx

from aether_vnext.provider_discovery import DiscoveryInstrument


KRAKEN_REST_BASE = "https://api.kraken.com"
ASSET_PAIRS_PATH = "/0/public/AssetPairs"
TICKER_PATH = "/0/public/Ticker"


def _num(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _precision_step(value: object) -> float | None:
    try:
        decimals = int(value)
    except (TypeError, ValueError):
        return None
    if decimals < 0 or decimals > 18:
        return None
    return 10.0 ** (-decimals)


def parse_kraken_spot_catalog(payload: object) -> dict[str, dict[str, object]]:
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
        wsname = str(raw.get("wsname") or "").strip().upper()
        altname = str(raw.get("altname") or pair_key).strip()
        if not wsname or "/" not in wsname or ".d" in str(pair_key).lower():
            continue
        base_display, quote_display = wsname.split("/", 1)
        out[str(pair_key)] = {
            "pair_key": str(pair_key),
            "symbol": wsname,
            "altname": altname,
            "base": str(raw.get("base") or ""),
            "quote": str(raw.get("quote") or ""),
            "base_display": base_display,
            "quote_display": quote_display,
            "ordermin": raw.get("ordermin"),
            "costmin": raw.get("costmin"),
            "pair_decimals": raw.get("pair_decimals"),
            "lot_decimals": raw.get("lot_decimals"),
        }
    return out


def parse_kraken_usd_catalog(payload: object) -> dict[str, dict[str, object]]:
    """Backward-compatible USD subset parser used by focused unit tests."""
    full = parse_kraken_spot_catalog(payload)
    return {
        key: row
        for key, row in full.items()
        if str(row.get("quote_display") or "").upper() == "USD"
    }


def _ticker_row_for(
    meta: Mapping[str, object],
    ticker_rows: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object] | None:
    pair_key = str(meta.get("pair_key") or "")
    altname = str(meta.get("altname") or "")
    return ticker_rows.get(pair_key) or ticker_rows.get(altname)


def _last_price(raw: Mapping[str, object] | None) -> float | None:
    if raw is None:
        return None
    last_arr = raw.get("c")
    return _num(last_arr[0] if isinstance(last_arr, list) and last_arr else None)


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

    cross_prices: dict[tuple[str, str], float] = {}
    for meta in catalog.values():
        raw = _ticker_row_for(meta, ticker_rows)
        last = _last_price(raw)
        if last is None or last <= 0:
            continue
        base = str(meta.get("base_display") or "").upper()
        quote = str(meta.get("quote_display") or "").upper()
        if base and quote:
            cross_prices[(base, quote)] = last

    def usd_per(currency: str) -> float | None:
        code = currency.upper()
        if code == "USD":
            return 1.0
        direct = cross_prices.get((code, "USD"))
        if direct is not None and direct > 0:
            return direct
        inverse = cross_prices.get(("USD", code))
        if inverse is not None and inverse > 0:
            return 1.0 / inverse
        return None

    out: list[DiscoveryInstrument] = []
    for meta in catalog.values():
        raw = _ticker_row_for(meta, ticker_rows)
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
        base_volume = _num(
            volume_arr[-1] if isinstance(volume_arr, list) and volume_arr else None
        )
        bid = _num(bid_arr[0] if isinstance(bid_arr, list) and bid_arr else None)
        ask = _num(ask_arr[0] if isinstance(ask_arr, list) and ask_arr else None)
        change = (
            None
            if last is None or open_price is None or open_price <= 0
            else ((last - open_price) / open_price) * 100.0
        )
        quote = str(meta.get("quote_display") or "").upper()
        quote_usd = usd_per(quote)
        volume_usd = (
            None
            if (
                base_volume is None
                or last is None
                or quote_usd is None
            )
            else base_volume * last * quote_usd
        )
        out.append(
            DiscoveryInstrument(
                provider="Kraken",
                symbol=str(meta["symbol"]),
                market_data_symbol=str(meta["symbol"]),
                execution_symbol=str(meta["altname"]),
                asset_class="spot_crypto",
                base_currency=str(meta.get("base_display") or "").upper() or None,
                quote_currency=str(meta.get("quote_display") or "").upper() or None,
                quantity_step=_precision_step(meta.get("lot_decimals")),
                minimum_quantity=_num(meta.get("ordermin")),
                minimum_notional=_num(meta.get("costmin")),
                tick_size=_precision_step(meta.get("pair_decimals")),
                active=True,
                price=last,
                open_price=open_price,
                high_price=high,
                low_price=low,
                volume=volume_usd,
                bid=bid,
                ask=ask,
                change_pct=change,
                observed_at_utc=observed_at_utc,
                source="kraken_public_rest",
                feed_class="NATIVE_PUBLIC",
                execution_quality=False,
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
        timeout=httpx.Timeout(20.0),
    )
    try:
        response = await http.get(ASSET_PAIRS_PATH)
        response.raise_for_status()
        catalog = parse_kraken_spot_catalog(response.json())
        keys = tuple(catalog)
        payloads: list[object] = []
        for start in range(0, len(keys), ticker_chunk_size):
            chunk = keys[start:start + ticker_chunk_size]
            ticker = await http.get(TICKER_PATH, params={"pair": ",".join(chunk)})
            ticker.raise_for_status()
            payloads.append(ticker.json())
            if start + ticker_chunk_size < len(keys):
                await asyncio.sleep(0.05)
        return parse_kraken_tickers(
            catalog,
            payloads,
            observed_at_utc=datetime.now(timezone.utc),
        )
    finally:
        if owned:
            await http.aclose()


async def fetch_kraken_spot_pair_facts(
    *,
    canonical_symbols: tuple[str, ...],
    client: httpx.AsyncClient | None = None,
) -> dict[str, dict[str, object]]:
    """Fetch identity/market-structure facts only from Kraken AssetPairs.

    This intentionally avoids the full ticker universe. Market Truth bootstrap needs
    no prices here; it needs only tick/lot/session identity facts for routed assets.
    """
    wanted = {str(symbol).strip().upper() for symbol in canonical_symbols if str(symbol).strip()}
    if not wanted:
        raise ValueError("at least one canonical symbol is required")
    owned = client is None
    http = client or httpx.AsyncClient(
        base_url=KRAKEN_REST_BASE,
        timeout=httpx.Timeout(10.0),
    )
    try:
        response = await http.get(ASSET_PAIRS_PATH)
        response.raise_for_status()
        catalog = parse_kraken_spot_catalog(response.json())
        by_symbol = {
            str(row.get("symbol") or "").strip().upper(): row
            for row in catalog.values()
        }
        out: dict[str, dict[str, object]] = {}
        for symbol in wanted:
            row = by_symbol.get(symbol)
            if row is None and symbol == "BTC/USD":
                row = by_symbol.get("XBT/USD")
            if row is None:
                continue
            out[symbol] = {
                **row,
                "tick_size": _precision_step(row.get("pair_decimals")),
                "quantity_step": _precision_step(row.get("lot_decimals")),
            }
        return out
    finally:
        if owned:
            await http.aclose()
