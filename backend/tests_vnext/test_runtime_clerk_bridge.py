from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.exit_plan import ExitPlan, ProfitTakePolicy, TrailingPolicy
from aether_vnext.runtime_clerk_bridge import evaluate_and_persist_clerk_ready
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)


def _obs() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-runtime-clerk",
        asset_id="eurusd",
        venue="test",
        bid=1.1000,
        ask=1.1002,
        last=1.1001,
        mark=1.1001,
        source="test",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=0,
        spread_abs=0.0002,
        spread_bps=1.818,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="test",
    )


def _plan() -> ExitPlan:
    return ExitPlan(
        exit_plan_id="exit-runtime-clerk",
        version="runtime-exit-v1",
        hard_stop_price=1.0950,
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


def _fixture() -> tuple[sa.Engine, VNextStore, MarketObservation]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    obs = _obs()
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-runtime-clerk",
                policy_version="policy-runtime-clerk",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="runtime clerk bridge",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, obs)
        conn.execute(
            store.tables["decision_lineage"].insert().values(
                firm_event_id="firm-runtime-clerk",
                setup_id="setup-runtime-clerk",
                ticket_id="ticket-runtime-clerk",
                order_intent_id=None,
                trade_id=None,
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                playbook_id="pb_fx_intraday_v1_2",
                playbook_version="1.2",
                risk_cluster_id="fx",
                asset_risk_hitches={},
                policy_version="policy-runtime-clerk",
                configuration_hash="cfg-runtime-clerk",
                market_observation_id=obs.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
                row_version=1,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-runtime-clerk",
                exit_plan_id=None,
                setup_id="setup-runtime-clerk",
                firm_event_id="firm-runtime-clerk",
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                state="SIZE",
                signal_key="signal-runtime-clerk",
                side="long",
                horizon="intraday",
                stop_price=1.0950,
                quantity=0.10,
                modeled_round_trip_cost_pct=None,
                reject_code=None,
                policy_version="policy-runtime-clerk",
                configuration_hash="cfg-runtime-clerk",
                market_observation_id=obs.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store, obs


def test_runtime_clerk_bridge_advances_size_to_ready_without_resizing() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        decision, result = evaluate_and_persist_clerk_ready(
            conn,
            store,
            ticket_id="ticket-runtime-clerk",
            current_observation=obs,
            first_target_price=1.1030,
            atr=None,
            locate_ok=False,
            exit_plan=_plan(),
            created_at_utc=T0,
            event_id="evt-runtime-clerk",
        )
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-clerk",
        )

    assert decision.ready is True
    assert result["state"] == "READY"
    assert result["quantity"] == pytest.approx(0.10)
    assert ticket is not None
    assert ticket.state.value == "READY"
    assert ticket.quantity == pytest.approx(0.10)
    assert ticket.exit_plan_id == "exit-runtime-clerk"
    assert ticket.modeled_round_trip_cost_pct is not None


def test_runtime_clerk_bridge_persists_cost_rejection_without_exit_plan() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        decision, result = evaluate_and_persist_clerk_ready(
            conn,
            store,
            ticket_id="ticket-runtime-clerk",
            current_observation=obs,
            first_target_price=1.10021,
            atr=None,
            locate_ok=False,
            exit_plan=None,
            created_at_utc=T0,
            event_id="evt-runtime-clerk-reject",
        )
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-clerk",
        )

    assert decision.ready is False
    assert decision.reject_code == "cost_hurdle_exceeds_expected_move"
    assert result["state"] == "REJECTED"
    assert ticket is not None
    assert ticket.state.value == "REJECTED"
    assert ticket.quantity == pytest.approx(0.10)
    assert ticket.exit_plan_id is None


def test_runtime_clerk_bridge_requires_size_ticket_and_current_asset() -> None:
    engine, store, obs = _fixture()
    wrong = MarketObservation(
        **{
            **{
                field: getattr(obs, field)
                for field in obs.__dataclass_fields__
            },
            "asset_id": "usdjpy",
        }
    )
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="asset mismatch"):
            evaluate_and_persist_clerk_ready(
                conn,
                store,
                ticket_id="ticket-runtime-clerk",
                current_observation=wrong,
                first_target_price=1.1030,
                atr=None,
                locate_ok=False,
                exit_plan=_plan(),
                created_at_utc=T0,
                event_id="evt-runtime-clerk-bad-asset",
            )

    engine2, store2, obs2 = _fixture()
    with engine2.begin() as conn:
        conn.execute(
            store2.tables["tickets"].update()
            .where(
                store2.tables["tickets"].c.ticket_id
                == "ticket-runtime-clerk"
            )
            .values(state="FIRE")
        )
        with pytest.raises(ValueError, match="requires SIZE"):
            evaluate_and_persist_clerk_ready(
                conn,
                store2,
                ticket_id="ticket-runtime-clerk",
                current_observation=obs2,
                first_target_price=1.1030,
                atr=None,
                locate_ok=False,
                exit_plan=_plan(),
                created_at_utc=T0,
                event_id="evt-runtime-clerk-wrong-state",
            )
