from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_vnext.operator_floor import (
    AttentionStation,
    FloorUniverseStation,
    SeatQueueSnapshot,
    UnifiedFirmFloorSnapshot,
)
from aether_vnext.operator_floor_api import create_operator_floor_router


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 17, 30, tzinfo=UTC)


def _snapshot() -> UnifiedFirmFloorSnapshot:
    station = FloorUniverseStation(
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
    )
    return UnifiedFirmFloorSnapshot(
        as_of_utc=T0,
        full_universe=(station,),
        top12_attention=(
            AttentionStation(
                rank=1,
                asset_id="btc",
                attention_basis_ref="attention-1",
                dominant_state="WATCH",
                seat_owner="Scout",
                first_blocker="no_trigger",
            ),
        ),
        seat_queues=(
            SeatQueueSnapshot(
                seat="Scout",
                state="WATCH",
                item_ids=("opp-1",),
                blocker_count=1,
            ),
        ),
        open_cockpits=(),
    )


def _client(*, runtime_started_at_utc: datetime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_operator_floor_router(
            _snapshot,
            runtime_started_at_utc=runtime_started_at_utc,
        )
    )
    return TestClient(app)


def test_floor_router_exposes_exact_read_only_contract_path() -> None:
    response = _client().get("/api/v1/vnext/floor")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == {"paper_only": True, "live_blocked": True}
    assert body["authority"]["read_only_projection"] is True
    assert body["authority"]["execution_permission"] is False
    assert body["full_universe"][0]["asset_id"] == "btc"
    assert body["top12_attention"][0]["rank"] == 1
    assert body["seat_queues"][0]["seat"] == "Scout"


def test_floor_router_exposes_no_mutation_method() -> None:
    client = _client()
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/v1/vnext/floor")
        assert response.status_code == 405


def test_floor_router_has_no_legacy_runtime_import() -> None:
    import aether_vnext.operator_floor_api as module

    source = module.__loader__.get_source(module.__name__)
    assert "from app" not in source
    assert "import app" not in source


def test_floor_router_exposes_fixed_runtime_start_separate_from_snapshot_time() -> None:
    runtime_started = datetime(2026, 9, 29, 17, 0, tzinfo=UTC)
    client = _client(runtime_started_at_utc=runtime_started)

    first = client.get("/api/v1/vnext/floor").json()
    second = client.get("/api/v1/vnext/floor").json()

    assert first["runtime_started_at_utc"] == runtime_started.isoformat()
    assert second["runtime_started_at_utc"] == runtime_started.isoformat()
    assert first["as_of_utc"] == T0.isoformat()
    assert second["as_of_utc"] == T0.isoformat()
    assert first["runtime_started_at_utc"] != first["as_of_utc"]


def test_floor_router_rejects_naive_runtime_start_timestamp() -> None:
    app = FastAPI()
    try:
        create_operator_floor_router(
            _snapshot,
            runtime_started_at_utc=datetime(2026, 9, 29, 17, 0),
        )
    except ValueError as exc:
        assert str(exc) == "runtime_started_at_utc must be timezone-aware"
    else:
        raise AssertionError("naive runtime start timestamp must be rejected")


def test_floor_router_exposes_build_identity_shape() -> None:
    body = _client().get("/api/v1/vnext/floor").json()
    assert set(body["build"]) == {
        "source_revision",
        "package_built_at_utc",
    }
