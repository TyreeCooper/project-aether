"""Massive market-universe adapter for AETHER provider discovery.

Massive is used here as a scouting/reference feed, not as an execution venue.
The execution-provider buckets remain Kraken, tastyfx, NinjaTrader, and IBKR.
No API key value is stored in code.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Mapping
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import httpx

from aether_vnext.provider_discovery import DiscoveryInstrument


MASSIVE_BASE_URL = "https://api.massive.com"
REFERENCE_TICKERS_PATH = "/v3/reference/tickers"
STOCK_SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
FOREX_SNAPSHOT_PATH = "/v2/snapshot/locale/global/markets/forex/tickers"
FUTURES_CONTRACTS_PATH = "/futures/v1/contracts"
FUTURES_SNAPSHOT_PATH = "/futures/v1/snapshot"


def configured_massive_api_key() -> str:
    return os.getenv("AETHER_MASSIVE_API_KEY", "").strip()


def _num(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    for key in ("results", "tickers"):
        raw = payload.get(key)
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, Mapping)]
    return []


def _bar(raw: object) -> Mapping[str, object]:
    return raw if isinstance(raw, Mapping) else {}


def _snapshot_instrument(
    *,
    provider: str,
    asset_class: str,
    ticker: str,
    raw: Mapping[str, object],
    name: str | None = None,
    execution_symbol: str | None = None,
    product_code: str | None = None,
    source: str,
    observed_at_utc: datetime,
) -> DiscoveryInstrument:
    day = _bar(raw.get("day"))
    prev = _bar(raw.get("prevDay"))
    quote = _bar(raw.get("lastQuote"))
    trade = _bar(raw.get("lastTrade"))
    minute = _bar(raw.get("min"))

    price = (
        _num(trade.get("p"))
        or _num(minute.get("c"))
        or _num(day.get("c"))
        or _num(raw.get("last_price"))
        or _num(raw.get("price"))
    )
    open_price = _num(day.get("o")) or _num(raw.get("open"))
    high = _num(day.get("h")) or _num(raw.get("high"))
    low = _num(day.get("l")) or _num(raw.get("low"))
    volume = _num(day.get("v")) or _num(raw.get("volume"))
    bid = _num(quote.get("p")) or _num(quote.get("bid")) or _num(raw.get("bid"))
    ask = _num(quote.get("P")) or _num(quote.get("ask")) or _num(raw.get("ask"))
    change_pct = _num(raw.get("todaysChangePerc"))
    if change_pct is None and price is not None:
        previous_close = _num(prev.get("c"))
        if previous_close is not None and previous_close > 0:
            change_pct = ((price - previous_close) / previous_close) * 100.0

    return DiscoveryInstrument(
        provider=provider,
        symbol=ticker,
        market_data_symbol=ticker,
        execution_symbol=execution_symbol,
        asset_class=asset_class,
        name=name,
        product_code=product_code,
        active=True,
        price=price,
        open_price=open_price,
        high_price=high,
        low_price=low,
        volume=volume,
        bid=bid,
        ask=ask,
        change_pct=change_pct,
        observed_at_utc=observed_at_utc,
        source=source,
    )


def parse_massive_stock_snapshot(payload: object, *, observed_at_utc: datetime) -> tuple[DiscoveryInstrument, ...]:
    out: list[DiscoveryInstrument] = []
    for raw in _rows(payload):
        ticker = str(raw.get("ticker") or "").strip()
        if not ticker:
            continue
        out.append(_snapshot_instrument(
            provider="IBKR",
            asset_class="equity",
            ticker=ticker,
            execution_symbol=ticker,
            raw=raw,
            source="massive_stock_snapshot",
            observed_at_utc=observed_at_utc,
        ))
    return tuple(out)


def parse_massive_forex_snapshot(payload: object, *, observed_at_utc: datetime) -> tuple[DiscoveryInstrument, ...]:
    out: list[DiscoveryInstrument] = []
    for raw in _rows(payload):
        ticker = str(raw.get("ticker") or "").strip()
        if not ticker:
            continue
        out.append(_snapshot_instrument(
            provider="tastyfx",
            asset_class="fx",
            ticker=ticker,
            execution_symbol=None,
            raw=raw,
            source="massive_forex_snapshot",
            observed_at_utc=observed_at_utc,
        ))
    return tuple(out)


def parse_massive_futures_contracts(payload: object) -> tuple[dict[str, object], ...]:
    out: list[dict[str, object]] = []
    for raw in _rows(payload):
        ticker = str(raw.get("ticker") or "").strip()
        product_code = str(raw.get("product_code") or "").strip()
        if not ticker or not product_code or raw.get("active") is False:
            continue
        days = raw.get("days_to_maturity")
        try:
            days_to_maturity = int(days) if days is not None else 10**9
        except (TypeError, ValueError):
            days_to_maturity = 10**9
        if days_to_maturity < 2:
            continue
        out.append({
            "ticker": ticker,
            "product_code": product_code,
            "name": str(raw.get("name") or ticker),
            "days_to_maturity": days_to_maturity,
            "trading_venue": str(raw.get("trading_venue") or ""),
            "trade_tick_size": raw.get("trade_tick_size"),
        })
    return tuple(out)


def front_contracts_by_product(rows: tuple[dict[str, object], ...]) -> dict[str, dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        code = str(row["product_code"])
        current = selected.get(code)
        if current is None or int(row["days_to_maturity"]) < int(current["days_to_maturity"]):
            selected[code] = row
    return selected


def parse_massive_futures_snapshot(
    payload: object,
    *,
    contracts: Mapping[str, Mapping[str, object]],
    observed_at_utc: datetime,
) -> tuple[DiscoveryInstrument, ...]:
    out: list[DiscoveryInstrument] = []
    for raw in _rows(payload):
        ticker = str(raw.get("ticker") or "").strip()
        if not ticker or ticker not in contracts:
            continue
        meta = contracts[ticker]
        out.append(_snapshot_instrument(
            provider="NinjaTrader",
            asset_class="future",
            ticker=ticker,
            execution_symbol=ticker,
            product_code=str(meta.get("product_code") or ""),
            name=str(meta.get("name") or ticker),
            raw=raw,
            source="massive_futures_snapshot",
            observed_at_utc=observed_at_utc,
        ))
    return tuple(out)


def _with_api_key(url: str, api_key: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["apiKey"] = api_key
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _get_json(
    client: httpx.AsyncClient,
    path_or_url: str,
    *,
    api_key: str,
    params: dict[str, object] | None = None,
) -> object:
    query = dict(params or {})
    query["apiKey"] = api_key
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        response = await client.get(_with_api_key(path_or_url, api_key))
    else:
        response = await client.get(path_or_url, params=query)
    response.raise_for_status()
    return response.json()


async def _paged_rows(
    client: httpx.AsyncClient,
    path: str,
    *,
    api_key: str,
    params: dict[str, object],
    max_pages: int = 100,
) -> tuple[Mapping[str, object], ...]:
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    all_rows: list[Mapping[str, object]] = []
    next_url: str | None = path
    current_params: dict[str, object] | None = dict(params)
    pages = 0
    while next_url:
        pages += 1
        if pages > max_pages:
            raise RuntimeError("Massive pagination exceeded max_pages")
        payload = await _get_json(
            client,
            next_url,
            api_key=api_key,
            params=current_params,
        )
        all_rows.extend(_rows(payload))
        current_params = None
        if not isinstance(payload, Mapping):
            break
        raw_next = payload.get("next_url")
        next_url = str(raw_next) if raw_next else None
    return tuple(all_rows)


async def fetch_massive_provider_universes(
    *,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, tuple[DiscoveryInstrument, ...]]:
    if not str(api_key).strip():
        raise ValueError("Massive API key is required")
    owned = client is None
    http = client or httpx.AsyncClient(
        base_url=MASSIVE_BASE_URL,
        timeout=httpx.Timeout(30.0),
    )
    now = datetime.now(timezone.utc)
    try:
        stock_payload = await _get_json(
            http,
            STOCK_SNAPSHOT_PATH,
            api_key=api_key,
        )
        forex_payload = await _get_json(
            http,
            FOREX_SNAPSHOT_PATH,
            api_key=api_key,
        )

        contracts_raw = await _paged_rows(
            http,
            FUTURES_CONTRACTS_PATH,
            api_key=api_key,
            params={
                "active": "true",
                "limit": 1000,
                "sort": "ticker.asc",
            },
        )
        contracts = parse_massive_futures_contracts({"results": list(contracts_raw)})
        fronts = front_contracts_by_product(contracts)
        contracts_by_ticker = {
            str(row["ticker"]): row
            for row in fronts.values()
        }

        futures_payload = await _get_json(
            http,
            FUTURES_SNAPSHOT_PATH,
            api_key=api_key,
            params={"limit": 1000},
        )

        return {
            "IBKR": parse_massive_stock_snapshot(
                stock_payload,
                observed_at_utc=now,
            ),
            "tastyfx": parse_massive_forex_snapshot(
                forex_payload,
                observed_at_utc=now,
            ),
            "NinjaTrader": parse_massive_futures_snapshot(
                futures_payload,
                contracts=contracts_by_ticker,
                observed_at_utc=now,
            ),
        }
    finally:
        if owned:
            await http.aclose()
