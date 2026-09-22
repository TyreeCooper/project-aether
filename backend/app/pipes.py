"""Public market pipes for books Kraken does not list."""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.universe import ASSETS, BY_ID

QUOTE = "https://query1.finance.yahoo.com/v7/finance/quote"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "AetherDesk/1.0"}
QUOTE_TTL = 12.0
BAR_TTL = 30.0

YAHOO = {
    "eurusd": "EURUSD=X",
    "usdjpy": "USDJPY=X",
    "mes": "MES=F",
    "mnq": "MNQ=F",
    "mgc": "MGC=F",
    "mcl": "MCL=F",
    "us10y": "ZN=F",
    "nvda": "NVDA",
    "tsla": "TSLA",
    "pltr": "PLTR",
}
FALLBACK = {"mgc": "GC=F", "mcl": "CL=F", "us10y": "^TNX"}

_quote_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
_bar_cache: dict[str, tuple[float, list[dict[str, float | int]]]] = {}


def yahoo_symbol(asset_id: str) -> str | None:
    return YAHOO.get(str(asset_id).lower())


def _quote_row(raw: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    last = raw.get("regularMarketPrice") or raw.get("postMarketPrice") or raw.get("bid") or raw.get("ask")
    bid = raw.get("bid")
    ask = raw.get("ask")
    try:
        last_f = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_f = None
    try:
        bid_f = float(bid) if bid is not None else last_f
    except (TypeError, ValueError):
        bid_f = last_f
    try:
        ask_f = float(ask) if ask is not None else last_f
    except (TypeError, ValueError):
        ask_f = last_f
    if last_f is None and bid_f and ask_f:
        last_f = (bid_f + ask_f) / 2
    return {
        "id": asset["id"],
        "name": asset["name"],
        "symbol": asset["symbol"],
        "pair": asset["pair"],
        "tv": asset.get("tv"),
        "binance": asset.get("binance"),
        "paper": True,
        "source": "yahoo",
        "pipe": "public_yahoo",
        "yahoo": raw.get("symbol"),
        "last": last_f,
        "bid": bid_f,
        "ask": ask_f,
        "open_24h": raw.get("regularMarketOpen"),
        "high_24h": raw.get("regularMarketDayHigh"),
        "low_24h": raw.get("regularMarketDayLow"),
        "volume_24h": raw.get("regularMarketVolume"),
        "watch_last": last_f,
        "watch_bid": bid_f,
        "watch_ask": ask_f,
    }


async def fetch_yahoo_quotes() -> dict[str, dict[str, Any]]:
    global _quote_cache
    now = time.time()
    if _quote_cache and now - _quote_cache[0] < QUOTE_TTL:
        return _quote_cache[1]
    symbols = list(YAHOO.values()) + list(FALLBACK.values())
    async with httpx.AsyncClient(timeout=8.0, headers=HEADERS) as client:
        res = await client.get(QUOTE, params={"symbols": ",".join(symbols)})
        res.raise_for_status()
        payload = res.json()
    rows = ((payload.get("quoteResponse") or {}).get("result") or [])
    by_sym = {str(r.get("symbol")): r for r in rows if isinstance(r, dict)}
    out: dict[str, dict[str, Any]] = {}
    for asset in ASSETS:
        aid = str(asset["id"])
        raw = by_sym.get(YAHOO.get(aid) or "")
        if raw is None and aid in FALLBACK:
            raw = by_sym.get(FALLBACK[aid])
        if raw:
            out[aid] = _quote_row(raw, asset)
    _quote_cache = (now, out)
    return out


async def enrich_markets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        extra = await fetch_yahoo_quotes()
    except Exception:
        extra = _quote_cache[1] if _quote_cache else {}
    by_id = {str(i.get("id")): i for i in items}
    for asset in ASSETS:
        aid = str(asset["id"])
        row = by_id.get(aid)
        fresh = extra.get(aid)
        if row is None and fresh:
            items.append(fresh)
            continue
        if row is None:
            continue
        if row.get("last") is None and fresh:
            row.update({k: v for k, v in fresh.items() if v is not None})
        elif fresh and not row.get("source"):
            row["source"] = fresh.get("source")
            row["pipe"] = fresh.get("pipe")
    return items


async def fetch_yahoo_bars(asset_id: str, interval: str = "1m", limit: int = 240) -> list[dict[str, float | int]]:
    key = f"{asset_id}:{interval}:{limit}"
    hit = _bar_cache.get(key)
    now = time.time()
    if hit and now - hit[0] < BAR_TTL:
        return hit[1]
    symbol = YAHOO.get(str(asset_id).lower()) or FALLBACK.get(str(asset_id).lower())
    if not symbol:
        return []
    range_map = {
        "1m": "1d",
        "5m": "5d",
        "60m": "60m",
        "1h": "3mo",
        "1d": "2y",
    }
    url = CHART.format(symbol=symbol)
    async with httpx.AsyncClient(timeout=10.0, headers=HEADERS) as client:
        res = await client.get(url, params={"interval": interval, "range": range_map.get(interval, "1d")})
        res.raise_for_status()
        payload = res.json()
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens, highs, lows, closes, vols = (
        quote.get("open") or [],
        quote.get("high") or [],
        quote.get("low") or [],
        quote.get("close") or [],
        quote.get("volume") or [],
    )
    bars: list[dict[str, float | int]] = []
    for i, ts in enumerate(stamps):
        try:
            close = float(closes[i])
            if close <= 0:
                continue
            bars.append(
                {
                    "ts": int(ts),
                    "open": float(opens[i] or close),
                    "high": float(highs[i] or close),
                    "low": float(lows[i] or close),
                    "close": close,
                    "volume": float(vols[i] or 0),
                }
            )
        except (TypeError, ValueError, IndexError):
            continue
    out = bars[-limit:]
    _bar_cache[key] = (now, out)
    return out


def asset_id_from_pair(pair: str) -> str | None:
    raw = str(pair or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in BY_ID:
        return lower
    for asset in ASSETS:
        if raw in {str(asset.get("kraken") or ""), str(asset.get("pair") or ""), str(asset.get("symbol") or "")}:
            return str(asset["id"])
        if yahoo_symbol(str(asset["id"])) == raw:
            return str(asset["id"])
    return None
