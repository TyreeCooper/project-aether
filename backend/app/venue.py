"""Public tapes. No API keys. Kraken is the paper fill mark. Binance.US is watch-only."""
from __future__ import annotations

from typing import Any

import httpx

from app.universe import ASSETS, KRAKEN_PAIRS

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


def _book_quote(book: dict[str, Any]) -> dict[str, float] | None:
    try:
        return {
            "last": float(book["c"][0]),
            "bid": float(book["b"][0]),
            "ask": float(book["a"][0]),
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def parse_universe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        return []
    keys = list(result.keys())
    out: list[dict[str, Any]] = []
    for asset in ASSETS:
        pair = str(asset["kraken"])
        book = result.get(pair)
        if book is None:
            needle = pair.replace("XBT", "BTC")
            book = next(
                (
                    result[k]
                    for k in keys
                    if pair in k or needle in k or k.endswith(pair) or pair.endswith(k[-6:])
                ),
                None,
            )
        quote = _book_quote(book) if isinstance(book, dict) else None
        item = {
            "id": asset["id"],
            "name": asset["name"],
            "symbol": asset["symbol"],
            "pair": asset["pair"],
            "tv": asset["tv"],
            "paper": bool(asset["paper"]),
            "source": "kraken" if quote else None,
            "last": quote["last"] if quote else None,
            "bid": quote["bid"] if quote else None,
            "ask": quote["ask"] if quote else None,
        }
        out.append(item)
    return out


def parse_ohlc_bars(payload: dict[str, Any], limit: int = 720) -> list[dict[str, float | int]]:
    result = payload.get("result") or {}
    series = next((v for k, v in result.items() if k != "last" and isinstance(v, list)), [])
    bars: list[dict[str, float | int]] = []
    for row in series[-limit:]:
        try:
            bars.append(
                {
                    "ts": int(float(row[0])),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[6]) if len(row) > 6 else 0.0,
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return bars


def parse_ohlc_closes(payload: dict[str, Any], limit: int = 120) -> list[float]:
    return [float(b["close"]) for b in parse_ohlc_bars(payload, limit)]


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


async def fetch_markets() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        res = await client.get(KRAKEN_TICKER, params={"pair": KRAKEN_PAIRS})
        res.raise_for_status()
        return parse_universe(res.json())


async def fetch_bars(interval: int = 1, limit: int = 720) -> list[dict[str, float | int]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(KRAKEN_OHLC, params={"pair": PAIR, "interval": interval})
        res.raise_for_status()
        return parse_ohlc_bars(res.json(), limit)


async def fetch_closes() -> list[float]:
    bars = await fetch_bars(interval=1, limit=720)
    return [float(b["close"]) for b in bars]


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
