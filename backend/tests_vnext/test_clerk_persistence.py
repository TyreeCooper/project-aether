from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.clerk import evaluate_clerk_ready
from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.exit_plan import ExitPlan, ProfitTakePolicy, TrailingPolicy
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 6, 25, tzinfo=UTC)


def _observation() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-clerk",
        asset_id="eurusd",
        venue="tastyfx",
        bid=1.1000,
        ask=1.1002,
        last=1.1001,
        mark=1.1001,
        source="test.fix",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=0,
        spread_abs=0.0002,
        spread_bps=(0.0002 / 1.1001) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="test-v1",
    )


def _plan(*, hard_stop_price: float = 1.0950) -> ExitPlan:
    return ExitPlan(
        exit_plan_id="exit-clerk-1",
        version="exit-plan-test-v1",
        hard_stop_price=hard_stop_price,
        structure_rule_id=None,
        time_stop_deadline_utc=T0 + timedelta(minutes=180),
        trailing_policy=TrailingPolicy(
            enabled=False,
            start_condition=None,
            ratchet_rule=None,
            never_loosen=True,
        ),
        profit_take_policy=ProfitTakePolicy(
            enabled=False,
            rule_id=None,
        ),
        session_close_policy="hold",
        stale_mark_policy="hold",
        governor_halt_behavior="hold",
        created_from_playbook_version="1.2",
    )


def _fixture() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    observation = _observation()
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-clerk",
                policy_version="policy-clerk",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="clerk persistence",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, observation)
        conn.execute(
            store.tables["decision_lineage"].insert().values(
                firm_event_id="firm-clerk",
                setup_id="setup-clerk",
                ticket_id="ticket-clerk",
                order_intent_id=None,
                trade_id=None,
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                playbook_id="pb_fx_intraday_v1_2",
                playbook_version="1.2",
                risk_cluster_id="fx",
                asset_risk_hitches={},
                policy_version="policy-clerk",
                configuration_hash="cfg-clerk",
                market_observation_id="obs-clerk",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
                row_version=1,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-clerk",
                exit_plan_id=None,
                setup_id="setup-clerk",
                firm_event_id="firm-clerk",
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                state="SIZE",
                signal_key="signal-clerk",
                side="long",
                horizon="intraday",
                stop_price=1.0950,
                quantity=0.10,
                modeled_round_trip_cost_pct=None,
                reject_code=None,
                policy_version="policy-clerk",
                configuration_hash="cfg-clerk",
                market_observation_id="obs-clerk",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store


def _ready_decision():
    decision = evaluate_clerk_ready(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        entry_reference_price=1.1001,
        spread_abs=0.0002,
        first_target_price=1.1020,
        atr=None,
    )
    assert decision.ready is True
    assert decision.costs is not None
    return decision


def _reject_decision():
    decision = evaluate_clerk_ready(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        entry_reference_price=1.1001,
        spread_abs=0.0002,
        first_target_price=1.10011,
        atr=None,
    )
    assert decision.ready is False
    assert decision.reject_code == "cost_hurdle_exceeds_expected_move"
    return decision


def test_clerk_size_to_ready_persists_cost_and_exit_plan_without_resizing() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        result = store.apply_clerk_decision(
            conn,
            ticket_id="ticket-clerk",
            decision=_ready_decision(),
            market_observation_id="obs-clerk",
            exit_plan=_plan(),
            created_at_utc=T0,
            event_id="evt-clerk-ready",
        )
        ticket = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-clerk"
            )
        ).mappings().one()
        plan = conn.execute(
            sa.select(store.tables["exit_plans"]).where(
                store.tables["exit_plans"].c.exit_plan_id == "exit-clerk-1"
            )
        ).mappings().one()
        lineage = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id == "firm-clerk"
            )
        ).mappings().one()
        events = store.event_rows(conn)

    assert result["ok"] is True
    assert result["state"] == "READY"
    assert result["quantity"] == pytest.approx(0.10)
    assert ticket["state"] == "READY"
    assert ticket["quantity"] == pytest.approx(0.10)
    assert ticket["modeled_round_trip_cost_pct"] == pytest.approx(
        result["modeled_round_trip_cost_pct"]
    )
    assert ticket["exit_plan_id"] == "exit-clerk-1"
    assert plan["payload_hash"] == result["exit_plan_payload_hash"]
    assert plan["hard_stop_price"] == pytest.approx(1.0950)
    assert lineage["first_killed_by"] is None
    assert events[-1]["seat"] == "Clerk"
    assert events[-1]["prior_state"] == "SIZE"
    assert events[-1]["new_state"] == "READY"
    assert events[-1]["reason_code"] == "clerk.ready"


def test_clerk_rejection_is_durable_and_does_not_persist_exit_plan() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        result = store.apply_clerk_decision(
            conn,
            ticket_id="ticket-clerk",
            decision=_reject_decision(),
            market_observation_id="obs-clerk",
            exit_plan=None,
            created_at_utc=T0,
            event_id="evt-clerk-reject",
        )
        ticket = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-clerk"
            )
        ).mappings().one()
        lineage = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id == "firm-clerk"
            )
        ).mappings().one()
        plan_count = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["exit_plans"])
        ).scalar_one()

    assert result["ok"] is False
    assert result["state"] == "REJECTED"
    assert result["quantity"] == pytest.approx(0.10)
    assert ticket["state"] == "REJECTED"
    assert ticket["quantity"] == pytest.approx(0.10)
    assert ticket["exit_plan_id"] is None
    assert ticket["first_killed_by"] == "Clerk"
    assert ticket["first_kill_reason"] == "cost_hurdle_exceeds_expected_move"
    assert lineage["first_killed_by"] == "Clerk"
    assert plan_count == 0


def test_clerk_ready_rejects_exit_plan_stop_or_playbook_version_drift() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="hard stop"):
            store.apply_clerk_decision(
                conn,
                ticket_id="ticket-clerk",
                decision=_ready_decision(),
                market_observation_id="obs-clerk",
                exit_plan=_plan(hard_stop_price=1.0940),
                created_at_utc=T0,
                event_id="evt-stop-drift",
            )

    engine2, store2 = _fixture()
    with engine2.begin() as conn:
        with pytest.raises(ValueError, match="playbook_version"):
            store2.apply_clerk_decision(
                conn,
                ticket_id="ticket-clerk",
                decision=_ready_decision(),
                market_observation_id="obs-clerk",
                exit_plan=replace(
                    _plan(),
                    created_from_playbook_version="1.3",
                ),
                created_at_utc=T0,
                event_id="evt-version-drift",
            )


def test_exit_plan_identity_is_idempotent_but_payload_cannot_change() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        first = store.record_exit_plan(
            conn,
            _plan(),
            created_at_utc=T0,
        )
        second = store.record_exit_plan(
            conn,
            _plan(),
            created_at_utc=T0 + timedelta(seconds=1),
        )
        assert first == second
        with pytest.raises(RuntimeError, match="different payload"):
            store.record_exit_plan(
                conn,
                replace(_plan(), stale_mark_policy="flatten"),
                created_at_utc=T0 + timedelta(seconds=2),
            )


def test_clerk_persistence_requires_size_state_and_never_accepts_plan_on_reject() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        conn.execute(
            store.tables["tickets"].update()
            .where(store.tables["tickets"].c.ticket_id == "ticket-clerk")
            .values(state="FIRE")
        )
        with pytest.raises(ValueError, match="requires SIZE"):
            store.apply_clerk_decision(
                conn,
                ticket_id="ticket-clerk",
                decision=_ready_decision(),
                market_observation_id="obs-clerk",
                exit_plan=_plan(),
                created_at_utc=T0,
                event_id="evt-wrong-state",
            )

    engine2, store2 = _fixture()
    with engine2.begin() as conn:
        with pytest.raises(ValueError, match="must not persist"):
            store2.apply_clerk_decision(
                conn,
                ticket_id="ticket-clerk",
                decision=_reject_decision(),
                market_observation_id="obs-clerk",
                exit_plan=_plan(),
                created_at_utc=T0,
                event_id="evt-reject-plan",
            )
