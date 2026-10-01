from __future__ import annotations

import asyncio

from aether_vnext import db_runtime


def test_database_url_engine_uses_bounded_asyncpg_timeouts(monkeypatch) -> None:
    captured = {}

    class DummyEngine:
        async def dispose(self):
            return None

    def fake_create_async_engine(url, **kwargs):
        captured["url"] = str(url)
        captured["kwargs"] = kwargs
        return DummyEngine()

    monkeypatch.setattr(db_runtime, "create_async_engine", fake_create_async_engine)

    async def scenario() -> None:
        config = db_runtime.VNextDatabaseConfig(
            environment="burnin",
            database_url="postgresql://user:pass@db.example/aether",
        )
        async with db_runtime.open_vnext_engine(config):
            pass

    asyncio.run(scenario())

    assert captured["kwargs"]["connect_args"]["timeout"] == 8.0
    assert captured["kwargs"]["connect_args"]["command_timeout"] == 12.0
