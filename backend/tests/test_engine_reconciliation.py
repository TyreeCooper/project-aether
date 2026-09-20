import asyncio

from app.engine import PaperEngine
from app.state import BotState


def test_reconciliation_match_does_not_fault():
    async def run():
        engine = PaperEngine()
        result = await engine.reconcile_position(
            venue_btc=engine.btc,
            source="test",
        )
        return engine, result

    engine, result = asyncio.run(run())

    assert result["ok"] is True
    assert engine.state == BotState.OFFLINE.value
    assert engine.flatten_lock is False


def test_reconciliation_mismatch_trips_fault_and_lock():
    async def run():
        engine = PaperEngine()
        result = await engine.reconcile_position(
            venue_btc=0.01,
            source="test",
        )
        return engine, result

    engine, result = asyncio.run(run())

    assert result["ok"] is False
    assert result["reason"] == "position_mismatch"
    assert engine.state == BotState.FAULT.value
    assert engine.flatten_lock is True
