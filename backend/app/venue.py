"""Public tapes. No API keys. Kraken is the paper fill mark. Binance.US is watch-only."""
from __future__ import annotations

from typing import Any

import httpx

from app.universe import ASSETS, BY_ID

KRAKEN_TICKER = "https://api.kraken.com/0/public/Ticker"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
KRAKEN_ASSET_PAIRS = "https://api.kraken.com/0/public/AssetPairs"
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
            "volume_24h": float(book["v"][1]),
            "vwap_24h": float(book["p"][1]),
            "trades_24h": int(book["t"][1]),
            "low_24h": float(book["l"][1]),
            "high_24h": float(book["h"][1]),
            "open_24h": float(book["o"]),
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
                    if pair in k or needle in k or k.endswith(pair)
                ),
                None,
            )
        quote = _book_quote(book) if isinstance(book, dict) else None
        out.append(
            {
                "id": asset["id"],
                "name": asset["name"],
                "symbol": asset["symbol"],
                "pair": asset["pair"],
                "tv": asset["tv"],
                "binance": asset["binance"],
                "paper": bool(asset["paper"]),
                "source": "kraken" if quote else None,
                "last": quote["last"] if quote else None,
                "bid": quote["bid"] if quote else None,
                "ask": quote["ask"] if quote else None,
                "open_24h": quote["open_24h"] if quote else None,
                "high_24h": quote["high_24h"] if quote else None,
                "low_24h": quote["low_24h"] if quote else None,
                "volume_24h": quote["volume_24h"] if quote else None,
                "vwap_24h": quote["vwap_24h"] if quote else None,
                "trades_24h": quote["trades_24h"] if quote else None,
                "watch_last": None,
                "watch_bid": None,
                "watch_ask": None,
            }
        )
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


def parse_ohlc_closes(payload: dict[str, Any]) -> list[float]:
    """Backward-compatible close-only view used by existing tests/callers."""
    return [float(bar["close"]) for bar in parse_ohlc_bars(payload)]


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


def parse_kraken_asset_library(
    payload: dict[str, Any],
    search: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return online Kraken spot crypto/USD pairs suitable for Aether books."""
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        return []
    needle = str(search or "").strip().upper()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, meta in result.items():
        if not isinstance(meta, dict):
            continue
        wsname = str(meta.get("wsname") or "")
        altname = str(meta.get("altname") or key)
        status = str(meta.get("status") or "online").lower()
        if not wsname.endswith("/USD") or status != "online" or ".d" in str(key):
            continue
        symbol = wsname.split("/", 1)[0].upper()
        # Kraken uses XBT for Bitcoin internally; keep the familiar UI symbol.
        ui_symbol = "BTC" if symbol == "XBT" else symbol
        asset_id = ui_symbol.lower().replace(".", "-")
        haystack = f"{ui_symbol} {wsname} {altname} {key}".upper()
        if needle and needle not in haystack:
            continue
        if asset_id in seen:
            continue
        seen.add(asset_id)
        rows.append(
            {
                "id": asset_id,
                "name": ui_symbol,
                "symbol": ui_symbol,
                "pair": f"{ui_symbol}/USD",
                "kraken": altname,
                "kraken_key": str(key),
                "wsname": wsname,
                "tv": f"KRAKEN:{altname}",
                "binance": f"{ui_symbol}USD",
                "paper": True,
                "status": status,
                "already_added": asset_id in BY_ID,
            }
        )
    rows.sort(key=lambda row: (bool(row["already_added"]), str(row["symbol"])))
    return rows[: max(1, min(int(limit), 100))]


async def discover_kraken_assets(
    search: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(KRAKEN_ASSET_PAIRS)
        res.raise_for_status()
        return parse_kraken_asset_library(res.json(), search=search, limit=limit)


async def resolve_kraken_asset(kraken_pair: str) -> dict[str, Any] | None:
    pair = str(kraken_pair or "").strip().upper()
    if not pair:
        return None
    rows = await discover_kraken_assets(search=pair, limit=100)
    for row in rows:
        if pair in {
            str(row.get("kraken") or "").upper(),
            str(row.get("kraken_key") or "").upper(),
            str(row.get("wsname") or "").replace("/", "").upper(),
        }:
            return row
    return None


async def fetch_ticker() -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(KRAKEN_TICKER, params={"pair": PAIR})
        res.raise_for_status()
        return parse_ticker(res.json())


async def fetch_markets() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        pairs = ",".join(str(a["kraken"]) for a in ASSETS)
        res = await client.get(KRAKEN_TICKER, params={"pair": pairs})
        res.raise_for_status()
        items = parse_universe(res.json())
        try:
            books = await client.get(BINANCE_US_BOOK)
            if books.status_code == 200:
                rows = books.json()
                by_sym = {
                    str(r.get("symbol")): r
                    for r in rows
                    if isinstance(r, dict)
                }
                for item in items:
                    raw = by_sym.get(str(item.get("binance")))
                    parsed = parse_binance_book(raw) if raw else None
                    if parsed:
                        item["watch_last"] = parsed["last"]
                        item["watch_bid"] = parsed["bid"]
                        item["watch_ask"] = parsed["ask"]
        except Exception:
            pass
        return items


async def fetch_bars(
    interval: int = 1,
    limit: int = 720,
    pair: str = PAIR,
) -> list[dict[str, float | int]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(
            KRAKEN_OHLC, params={"pair": pair, "interval": interval}
        )
        res.raise_for_status()
        return parse_ohlc_bars(res.json(), limit)


async def fetch_asset(asset_id: str) -> dict[str, Any]:
    asset = BY_ID.get(asset_id)
    if not asset:
        return {}
    items = await fetch_markets()
    item = next((x for x in items if x["id"] == asset_id), None) or {
        "id": asset["id"],
        "name": asset["name"],
        "symbol": asset["symbol"],
        "pair": asset["pair"],
        "tv": asset["tv"],
        "paper": bool(asset["paper"]),
    }
    bars = await fetch_bars(interval=5, limit=80, pair=str(asset["kraken"]))
    closes = [float(b["close"]) for b in bars]
    return {"item": item, "closes": closes[-48:], "bars": len(bars)}


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
