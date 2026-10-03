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
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 21, 30, tzinfo=UTC)


def _obs() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-risk-size",
        asset_id="eurusd",
        venue="tastyfx",
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
        data_version="test-v1",
    )


def _fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    obs = _obs()
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-size",
                policy_version="policy-size",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="risk size",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, obs)
        conn.execute(
            store.tables["decision_lineage"].insert().values(
                firm_event_id="firm-size",
                setup_id="setup-size",
                ticket_id="ticket-size",
                order_intent_id=None,
                trade_id=None,
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                playbook_id="pb_fx_intraday_v1_2",
                playbook_version="1.2",
                risk_cluster_id="fx",
                asset_risk_hitches={},
                policy_version="policy-size",
                configuration_hash="cfg-size",
                market_observation_id="obs-risk-size",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
                row_version=1,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-size",
                exit_plan_id=None,
                setup_id="setup-size",
                firm_event_id="firm-size",
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                state="FIRE",
                signal_key="signal-size",
                side="long",
                horizon="intraday",
                stop_price=1.0950,
                quantity=None,
                modeled_round_trip_cost_pct=None,
                reject_code=None,
                policy_version="policy-size",
                configuration_hash="cfg-size",
                market_observation_id="obs-risk-size",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store, obs


def test_risk_transitions_fire_to_size_without_impersonating_clerk() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        result = store.size_fire_ticket(
            conn,
            ticket_id="ticket-size",
            market_observation_id="obs-risk-size",
            current_observations={"eurusd": obs},
            estimated_round_trip_cost_per_unit_usd=50.0,
            created_at_utc=T0,
            event_id="evt-risk-size",
        )
        row = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-size"
            )
        ).mappings().one()
        events = store.event_rows(conn)

    assert result["ok"] is True
    assert result["state"] == "SIZE"
    assert result["quantity"] > 0
    assert row["state"] == "SIZE"
    assert row["quantity"] == pytest.approx(result["quantity"])
    assert row["modeled_round_trip_cost_pct"] is None
    assert row["reject_code"] is None
    assert events[-1]["seat"] == "Risk"
    assert events[-1]["prior_state"] == "FIRE"
    assert events[-1]["new_state"] == "SIZE"


def test_risk_rejects_ticket_when_modeled_loss_cannot_fit_minimum_quantity() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        result = store.size_fire_ticket(
            conn,
            ticket_id="ticket-size",
            market_observation_id="obs-risk-size",
            current_observations={"eurusd": obs},
            estimated_round_trip_cost_per_unit_usd=100_000.0,
            created_at_utc=T0,
            event_id="evt-risk-reject",
        )
        row = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-size"
            )
        ).mappings().one()
        lineage = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id
                == "firm-size"
            )
        ).mappings().one()

    assert result == {
        "ok": False,
        "state": "REJECTED",
        "reject_code": "too_small",
    }
    assert row["state"] == "REJECTED"
    assert row["quantity"] is None
    assert row["first_killed_by"] == "Risk"
    assert row["first_kill_reason"] == "too_small"
    assert lineage["first_killed_by"] == "Risk"
    assert lineage["first_kill_reason"] == "too_small"


def test_risk_requires_fire_state_and_durable_playbook_identity() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        conn.execute(
            store.tables["tickets"].update()
            .where(store.tables["tickets"].c.ticket_id == "ticket-size")
            .values(state="SIZE")
        )
        with pytest.raises(ValueError, match="requires FIRE"):
            store.size_fire_ticket(
                conn,
                ticket_id="ticket-size",
                market_observation_id="obs-risk-size",
                current_observations={"eurusd": obs},
                estimated_round_trip_cost_per_unit_usd=0.0,
                created_at_utc=T0,
                event_id="evt-illegal",
            )
