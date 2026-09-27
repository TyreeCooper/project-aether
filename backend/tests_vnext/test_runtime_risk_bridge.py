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
from aether_vnext.runtime_risk_bridge import size_runtime_fire_ticket
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 7, 45, tzinfo=UTC)


def _obs(observation_id: str = "obs-risk-runtime") -> MarketObservation:
    return MarketObservation(
        observation_id=observation_id,
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


def _fixture() -> tuple[sa.Engine, VNextStore, MarketObservation]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    obs = _obs()
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-runtime-risk",
                policy_version="policy-runtime-risk",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="runtime risk bridge",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_market_observation(conn, obs)
        conn.execute(
            store.tables["decision_lineage"].insert().values(
                firm_event_id="firm-runtime-risk",
                setup_id="setup-runtime-risk",
                ticket_id="ticket-runtime-risk",
                order_intent_id=None,
                trade_id=None,
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                playbook_id="pb_fx_intraday_v1_2",
                playbook_version="1.2",
                risk_cluster_id="fx",
                asset_risk_hitches={},
                policy_version="policy-runtime-risk",
                configuration_hash="cfg-runtime-risk",
                market_observation_id=obs.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
                row_version=1,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-runtime-risk",
                exit_plan_id=None,
                setup_id="setup-runtime-risk",
                firm_event_id="firm-runtime-risk",
                asset_id="eurusd",
                route_id="eurusd:intraday:long",
                state="FIRE",
                signal_key="signal-runtime-risk",
                side="long",
                horizon="intraday",
                stop_price=1.0950,
                quantity=None,
                modeled_round_trip_cost_pct=None,
                reject_code=None,
                policy_version="policy-runtime-risk",
                configuration_hash="cfg-runtime-risk",
                market_observation_id=obs.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store, obs


def test_runtime_risk_bridge_advances_fire_to_size() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        result = size_runtime_fire_ticket(
            conn,
            store,
            ticket_id="ticket-runtime-risk",
            current_observation=obs,
            current_observations={"eurusd": obs},
            estimated_round_trip_cost_per_unit_usd=50.0,
            created_at_utc=T0,
            event_id="evt-runtime-risk",
        )
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-risk",
        )

    assert result["ok"] is True
    assert result["state"] == "SIZE"
    assert float(result["quantity"]) > 0
    assert ticket is not None
    assert ticket.state.value == "SIZE"
    assert ticket.quantity == pytest.approx(float(result["quantity"]))
    assert ticket.modeled_round_trip_cost_pct is None


def test_runtime_risk_bridge_rejects_inconsistent_market_snapshot_before_sizing() -> None:
    engine, store, obs = _fixture()
    different = _obs("obs-other")
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="must match current observation"):
            size_runtime_fire_ticket(
                conn,
                store,
                ticket_id="ticket-runtime-risk",
                current_observation=obs,
                current_observations={"eurusd": different},
                estimated_round_trip_cost_per_unit_usd=50.0,
                created_at_utc=T0,
                event_id="evt-runtime-risk",
            )
        row = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-runtime-risk"
            )
        ).mappings().one()

    assert row["state"] == "FIRE"
    assert row["quantity"] is None
