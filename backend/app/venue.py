"""Public tapes. No API keys. Kraken is the paper fill mark. Binance.US is watch-only."""

from __future__ import annotations

from typing import Any

import httpx

KRAKEN_TICKER = "https://api.kraken.com/0/public/Ticker"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
PAIR = "XBTUSD"
BINANCE_US_BOOK = "https://api.binance.us/api/v3/ticker/bookTicker"
BINANCE_US_LAST = "https://api.binance.us/api/v3/ticker/price"


def parse_ticker(payload: dict[str, Any]) -> dict[str, Any] | None:
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


def parse_binance_book(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        bid = float(payload["bidPrice"])
        ask = float(payload["askPrice"])
    except (KeyError, TypeError, ValueError):
        return None
    last = payload.get("lastPrice")
    try:
        last_f = float(last) if last is not None else (bid + ask) / 2
    except (TypeError, ValueError):
        last_f = (bid + ask) / 2
    return {
        "last": last_f,
        "bid": bid,
        "ask": ask,
        "source": "binance.us",
        "symbol": payload.get("symbol", "BTCUSD"),
    }


async def fetch_ticker() -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(KRAKEN_TICKER, params={"pair": PAIR})
        res.raise_for_status()
        return parse_ticker(res.json())


async def fetch_closes() -> list[float]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(KRAKEN_OHLC, params={"pair": PAIR, "interval": 1})
        res.raise_for_status()
        return parse_ohlc_closes(res.json())


async def fetch_binance_us() -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=8.0) as client:
        book = await client.get(BINANCE_US_BOOK, params={"symbol": "BTCUSD"})
        book.raise_for_status()
        parsed = parse_binance_book(book.json())
        if not parsed:
            return None
        try:
            last = await client.get(BINANCE_US_LAST, params={"symbol": "BTCUSD"})
            if last.status_code == 200:
                parsed["last"] = float(last.json()["price"])
        except Exception:
            pass
        return parsed
