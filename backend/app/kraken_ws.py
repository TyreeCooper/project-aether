"""Kraken public ticker websocket. No keys. Marks only. Not a fill."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

PAIR_TO_ID = {"BTC/USD": "btc", "ETH/USD": "eth", "XBT/USD": "btc"}
URL = "wss://ws.kraken.com/v2"


def _parse(msg: Any) -> list[dict[str, Any]]:
    if not isinstance(msg, dict):
        return []
    if msg.get("channel") != "ticker":
        return []
    rows = msg.get("data") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        aid = PAIR_TO_ID.get(symbol)
        if not aid:
            continue
        try:
            last = float(row.get("last") or row.get("close") or 0)
            bid = float(row.get("bid") or last)
            ask = float(row.get("ask") or last)
        except (TypeError, ValueError):
            continue
        if last <= 0:
            continue
        out.append(
            {
                "id": aid,
                "last": last,
                "bid": bid,
                "ask": ask,
                "source": "kraken-ws",
                "ts": int(time.time()),
            }
        )
    return out


async def stream(on_quote: Callable[[dict[str, Any]], None], log: Callable[[str, str], None] | None = None) -> None:
    try:
        import websockets
    except ImportError:
        if log:
            log("WARN", "websockets package missing; Kraken WS off")
        return
    sub = {
        "method": "subscribe",
        "params": {"channel": "ticker", "symbol": ["BTC/USD", "ETH/USD"]},
    }
    while True:
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                await ws.send(json.dumps(sub))
                if log:
                    log("INFO", "Kraken public WS subscribed BTC/USD ETH/USD")
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    for quote in _parse(payload):
                        on_quote(quote)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if log:
                log("WARN", f"Kraken WS reconnect in 3s: {exc}")
            await asyncio.sleep(3)
