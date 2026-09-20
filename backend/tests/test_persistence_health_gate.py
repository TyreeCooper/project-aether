import asyncio

from app.engine import PaperEngine
from app.state import BotState


class HealthyLedger:
    async def health(self):
        return True

    async def record_audit(self, event):
        return True

    async def load_latest_state(self, symbol):
        return None


class UnhealthyLedger:
    async def health(self):
        return False

    async def record_audit(self, event):
        return True

    async def load_latest_state(self, symbol):
        return None


def test_unhealthy_required_persistence_blocks_arm():
    async def run():
        engine = PaperEngine(ledger=UnhealthyLedger())  # type: ignore[arg-type]
        result = await engine.start_bot()
        return engine, result

    engine, result = asyncio.run(run())

    assert result == {"ok": False, "error": "persistence_unhealthy"}
    assert engine.state == BotState.OFFLINE.value
    assert engine.snapshot()["persistence_healthy"] is False


def test_healthy_required_persistence_allows_arm():
    async def run():
        engine = PaperEngine(ledger=HealthyLedger())  # type: ignore[arg-type]
        result = await engine.start_bot()
        return engine, result

    engine, result = asyncio.run(run())

    assert result["ok"] is True
    assert engine.state == BotState.IDLE.value
    assert engine.snapshot()["persistence_healthy"] is True
