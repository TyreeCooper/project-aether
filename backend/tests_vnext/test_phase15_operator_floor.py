from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.operator_floor import (
    AttentionStation,
    FloorUniverseStation,
    InspectionDrawer,
    OpenPositionCockpit,
    SeatQueueSnapshot,
    UnifiedFirmFloorSnapshot,
    build_unified_firm_floor,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 17, 0, tzinfo=UTC)


def _station(asset_id: str, state: str = "WATCH", seat: str = "Scout"):
    return FloorUniverseStation(
        asset_id=asset_id,
        symbol=asset_id.upper(),
        product_type="spot",
        dominant_state=state,
        seat_owner=seat,
        first_blocker=None,
        first_blocker_reason=None,
        mark=100.0,
        open_position_count=0,
        route_ids=(f"{asset_id}:1h:trend",),
    )


def test_floor_contains_full_universe_top12_queues_cockpits_and_drawer() -> None:
    universe = (_station("btc", "OPEN", "Floor"), _station("eth"))
    snapshot = UnifiedFirmFloorSnapshot(
        as_of_utc=T0,
        full_universe=universe,
        top12_attention=(
            AttentionStation(
                rank=1,
                asset_id="btc",
                attention_basis_ref="attention-snapshot-1",
                dominant_state="OPEN",
                seat_owner="Floor",
                first_blocker=None,
            ),
            AttentionStation(
                rank=2,
                asset_id="eth",
                attention_basis_ref="attention-snapshot-1",
                dominant_state="WATCH",
                seat_owner="Scout",
                first_blocker="no_trigger",
            ),
        ),
        seat_queues=(
            SeatQueueSnapshot(
                seat="Scout",
                state="WATCH",
                item_ids=("opp-eth",),
            ),
            SeatQueueSnapshot(
                seat="Portfolio",
                state="ORDER",
                item_ids=(),
            ),
        ),
        open_cockpits=(
            OpenPositionCockpit(
                position_key="btc:1h",
                trade_id="trade-btc",
                asset_id="btc",
                horizon="1h",
                side="long",
                quantity=0.01,
                average_entry_price=100.0,
                mark_price=101.0,
                hard_stop_price=98.0,
                opened_at_utc=T0,
            ),
        ),
        inspection_drawer=InspectionDrawer(
            asset_id="btc",
            station_ref="station-btc",
            market_observation_ref="obs-btc",
            decision_lineage_ref="lineage-btc",
            evidence_refs=("evidence-1",),
            blocker_refs=(),
        ),
    )

    floor = build_unified_firm_floor(snapshot)

    assert [row["asset_id"] for row in floor["full_universe"]] == ["btc", "eth"]
    assert [row["asset_id"] for row in floor["top12_attention"]] == ["btc", "eth"]
    assert floor["seat_queues"][0]["seat"] == "Scout"
    assert floor["open_cockpits"][0]["position_key"] == "btc:1h"
    assert floor["inspection_drawer"]["asset_id"] == "btc"
    assert floor["mode"] == {"paper_only": True, "live_blocked": True}
    assert floor["authority"]["execution_permission"] is False
    assert floor["authority"]["second_runtime"] is False


def test_top12_rank_is_caller_owned_not_computed_by_floor() -> None:
    snapshot = UnifiedFirmFloorSnapshot(
        as_of_utc=T0,
        full_universe=(_station("btc"), _station("eth")),
        top12_attention=(
            AttentionStation(
                rank=2,
                asset_id="btc",
                attention_basis_ref="ranked-upstream",
                dominant_state="WATCH",
                seat_owner="Scout",
                first_blocker=None,
            ),
            AttentionStation(
                rank=1,
                asset_id="eth",
                attention_basis_ref="ranked-upstream",
                dominant_state="WATCH",
                seat_owner="Scout",
                first_blocker=None,
            ),
        ),
        seat_queues=(),
        open_cockpits=(),
    )

    floor = build_unified_firm_floor(snapshot)
    assert [row["asset_id"] for row in floor["top12_attention"]] == ["eth", "btc"]
    assert all(row["attention_basis_ref"] == "ranked-upstream" for row in floor["top12_attention"])


def test_seat_queue_ownership_is_canonical() -> None:
    with pytest.raises(ValueError, match="state is not owned"):
        SeatQueueSnapshot(
            seat="Scout",
            state="READY",
            item_ids=(),
        )

    with pytest.raises(ValueError, match="canonical Floor queue"):
        SeatQueueSnapshot(
            seat="Review",
            state="WATCH",
            item_ids=(),
        )


def test_floor_rejects_assets_outside_full_universe() -> None:
    with pytest.raises(ValueError, match="top12_attention assets"):
        UnifiedFirmFloorSnapshot(
            as_of_utc=T0,
            full_universe=(_station("btc"),),
            top12_attention=(
                AttentionStation(
                    rank=1,
                    asset_id="eth",
                    attention_basis_ref="ranked-upstream",
                    dominant_state="WATCH",
                    seat_owner="Scout",
                    first_blocker=None,
                ),
            ),
            seat_queues=(),
            open_cockpits=(),
        )


def test_floor_cannot_enable_live_mode() -> None:
    with pytest.raises(ValueError, match="PAPER ONLY / LIVE BLOCKED"):
        UnifiedFirmFloorSnapshot(
            as_of_utc=T0,
            full_universe=(),
            top12_attention=(),
            seat_queues=(),
            open_cockpits=(),
            live_blocked=False,
        )
