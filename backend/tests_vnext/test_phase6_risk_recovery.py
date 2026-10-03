from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.restart import load_restart_snapshot
from aether_vnext.store import VNextStore, open_intent_idempotency_key


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 19, 50, tzinfo=UTC)


def _obs() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-btc-recovery",
        asset_id="btc",
        venue="Kraken",
        bid=99_990.0,
        ask=100_010.0,
        last=100_000.0,
        mark=100_000.0,
        source="kraken_public",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=10,
        spread_abs=20.0,
        spread_bps=2.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="v1",
    )


def _fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg",
                policy_version="policy-v1",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="recovery fixture",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, _obs())
        conn.execute(
            store.tables["exit_plans"].insert().values(
                exit_plan_id="exit-btc-recovery",
                version="v1",
                hard_stop_price=95_000.0,
                structure_rule_id=None,
                time_stop_deadline_utc=None,
                trailing_policy={
                    "enabled": False,
                    "start_condition": None,
                    "ratchet_rule": None,
                    "never_loosen": True,
                },
                profit_take_policy={"enabled": False, "rule_id": None},
                session_close_policy="hold",
                stale_mark_policy="hold",
                governor_halt_behavior="hold",
                created_from_playbook_version="1.4",
                payload_hash="hash-exit-btc-recovery",
                created_at_utc=T0,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-btc-recovery",
                exit_plan_id="exit-btc-recovery",
                setup_id="setup-btc-recovery",
                firm_event_id=None,
                asset_id="btc",
                route_id="btc:daily_swing:long",
                state="READY",
                signal_key="signal-btc-recovery",
                side="long",
                horizon="daily_swing",
                stop_price=95_000.0,
                quantity=0.001,
                modeled_round_trip_cost_pct=0.10,
                reject_code=None,
                policy_version="policy-v1",
                configuration_hash="cfg",
                market_observation_id="obs-btc-recovery",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store


def _reserve(conn, store: VNextStore):
    idem = open_intent_idempotency_key(
        ticket_id="ticket-btc-recovery",
        side="long",
        quantity=0.001,
        asset_id="btc",
        horizon="daily_swing",
        signal_key="signal-btc-recovery",
    )
    return store.reserve_risk_checked_open_intent(
        conn,
        order_intent_id="intent-btc-recovery",
        ticket_id="ticket-btc-recovery",
        firm_event_id=None,
        asset_id="btc",
        route_id="btc:daily_swing:long",
        broker_account_id="kraken_paper",
        broker="Kraken",
        venue="Kraken",
        symbol="XBTUSD",
        side="long",
        qty=0.001,
        order_type="MARKET_PAPER",
        reference_price=None,
        expected_fill=None,
        idempotency_key=idem,
        signal_key="signal-btc-recovery",
        position_key="btc:daily_swing",
        reserve_cash_usd=None,
        reserve_margin_usd=None,
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        exit_plan_id="exit-btc-recovery",
        submit_timeout_at=None,
        policy_version="policy-v1",
        configuration_hash="cfg",
        market_observation_id="obs-btc-recovery",
        created_at_utc=T0,
        event_id="evt-reserve-btc-recovery",
        actor="portfolio",
        risk_cluster_id="crypto",
        cluster_by_asset={"btc": "crypto"},
        current_observations={},
    )


def test_restart_snapshot_preserves_pending_risk_and_guard_read_only() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        reserved = _reserve(conn, store)
        assert reserved["state"] == "RESERVED"

    with engine.begin() as conn:
        first = load_restart_snapshot(conn, store=store)
        second = load_restart_snapshot(conn, store=store)

    assert len(first.risk_admission_guard) == 1
    assert first.risk_admission_guard[0]["scope_key"] == "firm"
    assert len(first.risk_admission_reservations) == 1
    assert first.risk_admission_reservations[0]["order_intent_id"] == (
        "intent-btc-recovery"
    )
    assert first.risk_admission_issues == ()
    assert second.risk_admission_reservations == (
        first.risk_admission_reservations
    )
    assert second.risk_admission_guard == first.risk_admission_guard


def test_fill_atomically_moves_risk_source_from_pending_to_open_trade() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        reserved = _reserve(conn, store)
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-btc-recovery",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=None,
            event_id="evt-submit-btc-recovery",
            actor="paper-adapter",
        )
        intent = conn.execute(
            sa.select(store.tables["order_intents"]).where(
                store.tables["order_intents"].c.order_intent_id
                == "intent-btc-recovery"
            )
        ).mappings().one()
        opened = store.finalize_filled_open(
            conn,
            order_intent_id="intent-btc-recovery",
            trade_id="trade-btc-recovery",
            setup_id="setup-btc-recovery",
            exit_plan_id="exit-btc-recovery",
            fill_market_observation_id="obs-btc-recovery",
            filled_at_utc=T0,
            filled_qty=0.001,
            avg_fill_price=float(intent["expected_fill_price"]),
            slippage_usd=0.0,
            slippage_bps=5.0,
            initial_stop_risk_usd=float(
                reserved["reserved_stop_risk_usd"]
            ),
            management_telemetry={},
            event_id="evt-fill-btc-recovery",
            actor="portfolio",
        )
        assert opened["state"] == "FILLED"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one() == 0

        open_risk = store.project_open_risk(
            conn,
            cluster_by_asset={"btc": "crypto"},
        )
        assert open_risk.portfolio_open_risk_usd == pytest.approx(
            reserved["reserved_stop_risk_usd"]
        )
        pending = store._pending_open_risk_exposure(
            conn,
            asset_id="btc",
            cluster_id="crypto",
        )
        assert pending.portfolio_open_risk_usd == 0.0
        assert store.risk_admission_reconciliation_issues(conn) == ()


def test_zero_fill_terminal_release_clears_pending_stop_risk() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _reserve(conn, store)
        result = store.release_order_reservation(
            conn,
            order_intent_id="intent-btc-recovery",
            terminal_state="REJECTED",
            reject_code="broker_reject",
            at_utc=T0,
            event_id="evt-reject-btc-recovery",
            actor="paper-adapter",
            first_killed_by="execution",
        )
        assert result["state"] == "REJECTED"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one() == 0
        assert store.risk_admission_reconciliation_issues(conn) == ()


def test_reconciliation_detects_missing_pending_risk_record() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _reserve(conn, store)
        conn.execute(
            store.tables["risk_admission_reservations"].delete()
        )
        assert store.risk_admission_reconciliation_issues(conn) == (
            "missing_pending_risk_reservation:intent-btc-recovery",
        )


def test_reconciliation_detects_risk_record_left_on_terminal_intent() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        _reserve(conn, store)
        conn.execute(
            store.tables["order_intents"].update()
            .where(
                store.tables["order_intents"].c.order_intent_id
                == "intent-btc-recovery"
            )
            .values(state="REJECTED", reject_code="broker_reject")
        )
        assert store.risk_admission_reconciliation_issues(conn) == (
            "risk_reservation_on_nonpending_intent:intent-btc-recovery",
        )


def test_missing_guard_is_visible_after_restart_and_not_recreated() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        conn.execute(store.tables["risk_admission_guard"].delete())

    with engine.begin() as conn:
        snapshot = load_restart_snapshot(conn, store=store)
        assert snapshot.risk_admission_guard == ()
        assert snapshot.risk_admission_issues == (
            "firm_risk_guard_count:0",
        )
        assert store.provision_seed_ledgers_once(conn) is False
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_guard"]
            )
        ).scalar_one() == 0
