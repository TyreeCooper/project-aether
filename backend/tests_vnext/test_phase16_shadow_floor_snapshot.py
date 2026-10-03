from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.freeze import CONFIGURATION_HASH
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
                playbook_id="pb-trend",
                playbook_version="v1",
                risk_cluster_id="crypto",
                asset_risk_hitches={},
                trigger_bar_close_exchange_ts=T0,
                exit_contract_complete=True,
                exit_contract_gap=None,
                invalidation=None,
                quality=None,
                intel_pack={},
                regime_tags={},
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


def test_dynamic_commissioned_product_is_first_class_floor_station() -> None:
    engine, store = _store()
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "execution_symbol": "SOLUSD",
            "asset_class": "spot_crypto",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.01,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="kraken_public_ticker_v2",
        stale_threshold_ms=15000,
    )
    assert projection.product is not None
    observation = MarketObservation(
        observation_id="obs-sol-shadow",
        asset_id="kraken:solusd",
        venue="Kraken",
        bid=149.0,
        ask=151.0,
        last=150.0,
        mark=150.0,
        source="kraken_public_ticker_v2",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=1,
        spread_abs=2.0,
        spread_bps=133.3333333333,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="v1",
    )

    with engine.begin() as conn:
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="dynamic-floor-test-v1",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="dynamic Floor projection",
                payload={},
                created_at_utc=T0,
            )
        )
        store.upsert_dynamic_product_state(
            conn,
            projection.product,
            source_ref="kraken_public_rest:SOLUSD",
            registry_version="dynamic-kraken-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        store.record_market_observation(conn, observation)
        conn.execute(
            store.tables["setups"].insert().values(
                setup_id="setup-sol-shadow",
                firm_event_id=None,
                asset_id="kraken:solusd",
                route_id="kraken:solusd:1h:trend",
                state="WATCH",
                side="long",
                horizon="1h",
                playbook_id="pb_crypto_swing_v1_2",
                playbook_version="v1",
                risk_cluster_id="crypto",
                asset_risk_hitches={},
                trigger_bar_close_exchange_ts=T0,
                exit_contract_complete=True,
                exit_contract_gap=None,
                invalidation=None,
                quality=None,
                intel_pack={},
                regime_tags={},
                policy_version="dynamic-floor-test-v1",
                configuration_hash=CONFIGURATION_HASH,
                market_observation_id=observation.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )

    with engine.begin() as conn:
        floor = build_shadow_floor_snapshot(conn, store=store, as_of_utc=T0)

    assert len(floor.full_universe) == 13
    sol = next(
        row for row in floor.full_universe
        if row.asset_id == "kraken:solusd"
    )
    assert sol.symbol == "SOL/USD"
    assert sol.dominant_state == "WATCH"
    assert sol.seat_owner == "Scout"
    assert sol.mark == 150.0
    assert sol.route_ids == ("kraken:solusd:1h:trend",)
    watch = next(
        row for row in floor.seat_queues
        if row.seat == "Scout" and row.state == "WATCH"
    )
    assert watch.item_ids == ("setup-sol-shadow",)
