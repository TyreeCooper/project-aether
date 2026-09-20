import asyncio
import time

from app.config import settings
from app.engine import PaperEngine
from app.state import BotState


def test_required_reconciliation_blocks_arm_until_matched():
    old_required = settings.venue_reconciliation_required
    old_age = settings.venue_reconciliation_max_age_seconds
    settings.venue_reconciliation_required = True
    settings.venue_reconciliation_max_age_seconds = 60
    try:
        async def run():
            engine = PaperEngine()
            denied = await engine.start_bot()
            matched = await engine.reconcile_position(
                venue_btc=engine.btc,
                source="test",
            )
            allowed = await engine.start_bot()
            return engine, denied, matched, allowed

        engine, denied, matched, allowed = asyncio.run(run())

        assert denied == {"ok": False, "error": "reconciliation_required"}
        assert matched["ok"] is True
        assert allowed["ok"] is True
        assert engine.state == BotState.IDLE.value
    finally:
        settings.venue_reconciliation_required = old_required
        settings.venue_reconciliation_max_age_seconds = old_age


def test_stale_reconciliation_blocks_arm():
    old_required = settings.venue_reconciliation_required
    old_age = settings.venue_reconciliation_max_age_seconds
    settings.venue_reconciliation_required = True
    settings.venue_reconciliation_max_age_seconds = 1
    try:
        async def run():
            engine = PaperEngine()
            engine._last_reconcile_ok = True
            engine._last_reconcile_mono = time.monotonic() - 2
            result = await engine.start_bot()
            return engine, result

        engine, result = asyncio.run(run())

        assert result == {"ok": False, "error": "reconciliation_required"}
        assert engine.state == BotState.OFFLINE.value
    finally:
        settings.venue_reconciliation_required = old_required
        settings.venue_reconciliation_max_age_seconds = old_age
