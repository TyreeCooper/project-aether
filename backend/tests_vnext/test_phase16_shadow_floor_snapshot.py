from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.shadow_floor_snapshot import (
    _build_open_cockpit,
    build_shadow_floor_snapshot,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 18, 30, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _obs() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-btc-shadow",
        asset_id="btc",
        venue="Kraken",
        bid=99.0,
        ask=101.0,
        last=100.0,
        mark=100.0,
        source="kraken_public",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=1,
        spread_abs=2.0,
        spread_bps=200.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="v1",
    )


def test_empty_book_projects_full_canonical_seed_universe_without_rank_invention() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        floor = build_shadow_floor_snapshot(conn, store=store, as_of_utc=T0)

    assert len(floor.full_universe) == 12
    assert {row.asset_id for row in floor.full_universe} == {
        "btc", "eth", "eurusd", "usdjpy", "mes", "mnq",
        "mgc", "mcl", "us10y", "nvda", "tsla", "pltr",
    }
    assert all(row.dominant_state == "NO" for row in floor.full_universe)
    assert floor.top12_attention == ()
    assert floor.open_cockpits == ()
    assert floor.paper_only is True
    assert floor.live_blocked is True


def test_watch_state_and_latest_mark_come_from_canonical_book() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_market_observation(conn, _obs())
        conn.execute(
            store.tables["setups"].insert().values(
                setup_id="setup-btc-shadow",
                firm_event_id=None,
                asset_id="btc",
                route_id="btc:1h:trend",
                state="WATCH",
                side="long",
                horizon="1h",
                invalidation=None,
                quality=None,
                intel_pack={},
                policy_version="policy-shadow",
                configuration_hash="cfg-shadow",
                market_observation_id="obs-btc-shadow",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )

    with engine.begin() as conn:
        floor = build_shadow_floor_snapshot(conn, store=store, as_of_utc=T0)

    btc = next(row for row in floor.full_universe if row.asset_id == "btc")
    assert btc.dominant_state == "WATCH"
    assert btc.seat_owner == "Scout"
    assert btc.mark == 100.0
    assert btc.route_ids == ("btc:1h:trend",)
    assert len(floor.seat_queues) == 1
    assert floor.seat_queues[0].seat == "Scout"
    assert floor.seat_queues[0].state == "WATCH"
    assert floor.seat_queues[0].item_ids == ("setup-btc-shadow",)


def test_desk_halt_overrides_display_state_without_mutating_book() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        conn.execute(
            store.tables["governor_state"].insert().values(
                scope_key="desk:firm",
                scope_type="desk",
                scope_id=None,
                governor_state_version="gov-v1",
                state="HALT",
                configuration_hash="cfg-shadow",
                effective_at_utc=T0,
                reason="operator halt",
                row_version=1,
            )
        )

    with engine.begin() as conn:
        floor = build_shadow_floor_snapshot(conn, store=store, as_of_utc=T0)

    assert all(row.dominant_state == "HALT" for row in floor.full_universe)
    assert all(row.seat_owner == "Governor" for row in floor.full_universe)
    halt_queue = next(
        row for row in floor.seat_queues
        if row.seat == "Governor" and row.state == "HALT"
    )
    assert halt_queue.item_ids == ("desk:firm",)


def test_open_cockpit_helper_preserves_canonical_identity_and_stop() -> None:
    cockpit = _build_open_cockpit(
        active={
            "position_key": "btc:1h",
            "trade_id": "trade-1",
            "asset_id": "btc",
            "horizon": "1h",
            "side": "long",
            "quantity": 0.01,
        },
        trade={
            "trade_id": "trade-1",
            "asset_id": "btc",
            "avg_entry_price": 100.0,
            "opened_at_utc": T0,
        },
        exit_plan={"hard_stop_price": 95.0},
        mark=101.0,
    )

    assert cockpit.position_key == "btc:1h"
    assert cockpit.trade_id == "trade-1"
    assert cockpit.average_entry_price == 100.0
    assert cockpit.mark_price == 101.0
    assert cockpit.hard_stop_price == 95.0
    assert cockpit.dominant_state == "OPEN"
