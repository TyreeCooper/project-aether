"""Public Kraken tape. No API keys. Used only as a paper mark."""

from __future__ import annotations

from typing import Any

import httpx

KRAKEN_TICKER = "https://api.kraken.com/0/public/Ticker"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
PAIR = "XBTUSD"


def parse_ticker(payload: dict[str, Any]) -> dict[str, float] | None:
    if payload.get("error"):
        return None
    result = payload.get("result") or {}
    book = next(iter(result.values()), None)
    if not isinstance(book, dict):
        return None
    try:
        last = float(book["c"][0])
        bid = float(book["b"][0])
        ask = float(book["a"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return {"last": last, "bid": bid, "ask": ask, "source": "kraken"}


def parse_ohlc_closes(payload: dict[str, Any], limit: int = 120) -> list[float]:
    result = payload.get("result") or {}
    series = next((v for v in result.values() if isinstance(v, list)), [])
    closes: list[float] = []
    for row in series[-limit:]:
        try:
            closes.append(float(row[4]))
        except (IndexError, TypeError, ValueError):
            continue
    return closes


async def fetch_ticker() -> dict[str, float] | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(KRAKEN_TICKER, params={"pair": PAIR})
        res.raise_for_status()
        return parse_ticker(res.json())


async def fetch_closes() -> list[float]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(KRAKEN_OHLC, params={"pair": PAIR, "interval": 1})
        res.raise_for_status()
        return parse_ohlc_closes(res.json())
