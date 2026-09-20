"""Kraken Spot WebSocket v2 public ticker provider.

The provider maintains a latest-mark cache from Kraken's public ticker stream
and uses CoinGecko only to seed the existing SMA warm-up history.

Reference:
Kraken WebSockets v2 public endpoint: wss://ws.kraken.com/v2
Subscription shape: {"method":"subscribe","params":{"channel":"ticker","symbol":["BTC/USD"]}}
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import websockets

from app.market_data.base import MarketDataProvider, MarketSnapshot
from app.market_data.coingecko import CoinGeckoMarketDataProvider


class KrakenWebSocketMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        *,
        url: str = "wss://ws.kraken.com/v2",
        connect_timeout_seconds: float = 10.0,
        stale_after_seconds: float = 30.0,
        seed_provider: MarketDataProvider | None = None,
    ) -> None:
        self.url = url
        self.connect_timeout_seconds = connect_timeout_seconds
        self.stale_after_seconds = stale_after_seconds
        self.seed_provider = seed_provider or CoinGeckoMarketDataProvider()
        self.source = "kraken_ws_v2"

        self._latest: MarketSnapshot | None = None
        self._latest_mono: float | None = None
        self._stream_task: asyncio.Task | None = None
        self._symbol: str | None = None
        self._ready = asyncio.Event()

    @staticmethod
    def subscription_message(symbol: str) -> dict[str, Any]:
        return {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": [symbol],
            },
        }

    @staticmethod
    def parse_ticker_message(
        message: str | bytes | dict[str, Any],
    ) -> MarketSnapshot | None:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        payload = json.loads(message) if isinstance(message, str) else message

        if payload.get("channel") != "ticker":
            return None

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            return None

        row = data[0]
        symbol = row.get("symbol")
        last = row.get("last")
        if not symbol or last is None:
            return None

        timestamp = row.get("timestamp")
        ts_ms: int | None = None
        if isinstance(timestamp, str):
            # Kraken timestamps are ISO-8601. Wall-clock parsing is not needed
            # for freshness because receipt time is tracked monotonically.
            ts_ms = None

        return MarketSnapshot(
            symbol=str(symbol),
            price=float(last),
            source="kraken_ws_v2",
            ts_ms=ts_ms,
        )

    def _is_fresh(self) -> bool:
        return (
            self._latest is not None
            and self._latest_mono is not None
            and (time.monotonic() - self._latest_mono) <= self.stale_after_seconds
        )

    async def _stream(self, symbol: str) -> None:
        while True:
            try:
                async with websockets.connect(
                    self.url,
                    open_timeout=self.connect_timeout_seconds,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=64,
                ) as ws:
                    await ws.send(json.dumps(self.subscription_message(symbol)))

                    async for raw in ws:
                        snapshot = self.parse_ticker_message(raw)
                        if snapshot is None:
                            continue
                        if snapshot.symbol != symbol:
                            continue

                        self._latest = snapshot
                        self._latest_mono = time.monotonic()
                        self._ready.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._ready.clear()
                await asyncio.sleep(2.0)

    def _ensure_stream(self, symbol: str) -> None:
        if self._stream_task is not None and not self._stream_task.done():
            return
        self._symbol = symbol
        self._stream_task = asyncio.create_task(self._stream(symbol))

    async def get_mark(self, symbol: str) -> MarketSnapshot | None:
        if self._symbol is not None and self._symbol != symbol:
            raise ValueError(
                f"Kraken WebSocket provider already bound to {self._symbol}, got {symbol}"
            )

        self._ensure_stream(symbol)
        if self._is_fresh():
            return self._latest

        try:
            await asyncio.wait_for(
                self._ready.wait(),
                timeout=self.connect_timeout_seconds,
            )
        except TimeoutError:
            return None

        return self._latest if self._is_fresh() else None

    async def get_seed_prices(self, symbol: str, limit: int = 120) -> list[float]:
        return await self.seed_provider.get_seed_prices(symbol, limit=limit)

    async def close(self) -> None:
        if self._stream_task is None:
            return
        self._stream_task.cancel()
        try:
            await self._stream_task
        except asyncio.CancelledError:
            pass
        finally:
            self._stream_task = None
