from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.vnext_shadow import mount_vnext_shadow_floor, shadow_floor_contract
from aether_vnext.operator_floor import (
    FloorUniverseStation,
    UnifiedFirmFloorSnapshot,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 0, tzinfo=UTC)


def _snapshot() -> UnifiedFirmFloorSnapshot:
    return UnifiedFirmFloorSnapshot(
        as_of_utc=T0,
        full_universe=(
            FloorUniverseStation(
                asset_id="btc",
                symbol="BTC/USD",
                product_type="spot",
                dominant_state="WATCH",
                seat_owner="Scout",
                first_blocker="no_trigger",
                first_blocker_reason="setup not fired",
                mark=100.0,
                open_position_count=0,
                route_ids=("btc:1h:trend",),
            ),
        ),
        top12_attention=(),
        seat_queues=(),
        open_cockpits=(),
    )


def test_shadow_mount_adds_get_only_floor_to_existing_app() -> None:
    app = FastAPI()

    @app.get("/api/v1/legacy-sentinel")
    def legacy_sentinel():
        return {"ok": True}

    mount_vnext_shadow_floor(app, snapshot_provider=_snapshot)
    client = TestClient(app)

    legacy = client.get("/api/v1/legacy-sentinel")
    floor = client.get("/api/v1/vnext/floor")

    assert legacy.status_code == 200
    assert legacy.json() == {"ok": True}
    assert floor.status_code == 200
    assert floor.json()["mode"] == {"paper_only": True, "live_blocked": True}

    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/vnext/floor").status_code == 405


def test_shadow_mount_contract_forbids_cutover_and_second_runtime() -> None:
    contract = shadow_floor_contract()
    assert contract == {
        "phase": 16,
        "mode": "shadow",
        "path": "/api/v1/vnext/floor",
        "read_only": True,
        "second_runtime": False,
        "paper_only": True,
        "live_blocked": True,
        "legacy_fallback_allowed": False,
        "database_source": "dedicated_aether_vnext_burnin",
        "mutation_methods": (),
    }
