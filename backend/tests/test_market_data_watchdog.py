import asyncio
import time

from app.engine import MAX_CONSECUTIVE_MARK_FAILURES, PaperEngine
from app.market_data.base import MarketDataProvider, MarketSnapshot
from app.state import BotState


class NoMarkProvider(MarketDataProvider):
    async def get_mark(self, symbol: str) -> MarketSnapshot | None:
        return None

    async def get_seed_prices(self, symbol: str, limit: int = 120) -> list[float]:
        return []


class FreshProvider(MarketDataProvider):
    async def get_mark(self, symbol: str) -> MarketSnapshot | None:
        return MarketSnapshot(symbol=symbol, price=50_000.0, source="fresh")

    async def get_seed_prices(self, symbol: str, limit: int = 120) -> list[float]:
        return []


def test_repeated_missing_marks_trip_fail_closed_fault():
    async def run():
        engine = PaperEngine(market_data=NoMarkProvider())
        await engine.start_bot()
        for _ in range(MAX_CONSECUTIVE_MARK_FAILURES):
            await engine.tick()
        return engine

    engine = asyncio.run(run())
    assert engine.state == BotState.FAULT.value
    assert engine.flatten_lock is True


def test_fault_reset_requires_fresh_market_data():
    async def run():
        engine = PaperEngine(market_data=FreshProvider())
        engine._set_state(BotState.FAULT)
        engine.flatten_lock = True

        denied = await engine.reset_fault()

        engine.mark = 50_000.0
        engine._last_tick_mono = time.monotonic()
        engine._consecutive_mark_failures = 0
        allowed = await engine.reset_fault()
        return engine, denied, allowed

    engine, denied, allowed = asyncio.run(run())

    assert denied == {"ok": False, "error": "market_data_not_fresh"}
    assert allowed["ok"] is True
    assert engine.state == BotState.OFFLINE.value
    assert engine.flatten_lock is False
