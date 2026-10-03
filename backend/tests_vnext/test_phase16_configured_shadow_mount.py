from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.vnext_shadow import (
    load_configured_vnext_shadow_snapshot,
    mount_configured_vnext_shadow_floor,
    mount_vnext_shadow_floor,
)
from aether_vnext.operator_floor import UnifiedFirmFloorSnapshot


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 19, 0, tzinfo=UTC)


def test_async_snapshot_provider_is_supported_by_get_only_router() -> None:
    async def provider() -> UnifiedFirmFloorSnapshot:
        return UnifiedFirmFloorSnapshot(
            as_of_utc=T0,
            full_universe=(),
            top12_attention=(),
            seat_queues=(),
            open_cockpits=(),
        )

    app = FastAPI()
    mount_vnext_shadow_floor(app, snapshot_provider=provider)
    client = TestClient(app)

    response = client.get("/api/v1/vnext/floor")
    assert response.status_code == 200
    assert response.json()["mode"] == {
        "paper_only": True,
        "live_blocked": True,
    }


def test_configured_shadow_mount_fails_closed_without_vnext_database(monkeypatch) -> None:
    for name in (
        "AETHER_VNEXT_ENVIRONMENT",
        "AETHER_VNEXT_DATABASE_URL",
        "AETHER_VNEXT_AZURE_POSTGRESQL_CONNECTIONSTRING",
    ):
        monkeypatch.delenv(name, raising=False)

    app = FastAPI()
    mount_configured_vnext_shadow_floor(app)
    client = TestClient(app)

    response = client.get("/api/v1/vnext/floor")
    assert response.status_code == 503
    assert "dedicated sandbox database configuration" in response.json()["detail"]

    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/vnext/floor").status_code == 405


def test_phase16_main_mounts_shadow_floor_without_legacy_fallback() -> None:
    backend = Path(__file__).resolve().parents[1]
    main = (backend / "app" / "main.py").read_text(encoding="utf-8")
    bridge = (backend / "app" / "vnext_shadow.py").read_text(encoding="utf-8")

    assert "mount_configured_vnext_shadow_floor(app)" in main
    assert "load_configured_vnext_shadow_snapshot" in bridge
    assert "open_vnext_engine" in bridge
    assert "build_shadow_floor_snapshot" in bridge
    assert "desk.floor_snapshot" not in bridge
    assert "legacy_fallback_allowed" in bridge
    assert "engine.start_loop" not in bridge



def test_configured_shadow_floor_times_out_as_503(monkeypatch) -> None:
    import asyncio
    from contextlib import asynccontextmanager

    from fastapi import HTTPException
    from app import vnext_shadow

    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    monkeypatch.setenv(
        "AETHER_VNEXT_DATABASE_URL",
        "postgresql+asyncpg://user:pass@example.invalid/aether",
    )

    @asynccontextmanager
    async def stalled_engine(_config):
        class Engine:
            @asynccontextmanager
            async def connect(self):
                await asyncio.sleep(20.0)
                yield None

            async def dispose(self):
                return None

        yield Engine()

    monkeypatch.setattr(vnext_shadow, "open_vnext_engine", stalled_engine)

    async def scenario() -> None:
        try:
            await asyncio.wait_for(
                load_configured_vnext_shadow_snapshot(),
                timeout=13.0,
            )
        except HTTPException as exc:
            assert exc.status_code == 503
            assert "timed out" in str(exc.detail)
        else:
            raise AssertionError("expected bounded 503 timeout")

    asyncio.run(scenario())
