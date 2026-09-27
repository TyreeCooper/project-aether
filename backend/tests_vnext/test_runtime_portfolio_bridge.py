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
from aether_vnext.runtime_portfolio_bridge import reserve_runtime_ready_ticket
from aether_vnext.store import VNextStore, open_intent_idempotency_key
from tests_vnext.runtime_registry_support import record_test_runtime_binding


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 8, 30, tzinfo=UTC)


def _obs() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-runtime-portfolio",
        asset_id="btc",
        venue="Kraken",
        bid=99_990.0,
        ask=100_010.0,
        last=100_000.0,
        mark=100_000.0,
        source="test.market.btc",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=0,
        spread_abs=20.0,
        spread_bps=2.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
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
                configuration_hash="cfg-runtime-portfolio",
                policy_version="policy-runtime-portfolio",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="runtime portfolio bridge",
                payload={},
                created_at_utc=T0,
            )
        )
        record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash="cfg-runtime-portfolio",
            now=T0,
        )
        store.record_market_observation(conn, obs)
        conn.execute(
            store.tables["exit_plans"].insert().values(
                exit_plan_id="exit-runtime-portfolio",
                version="runtime-exit-v1",
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
                created_from_playbook_version="1.2",
                payload_hash="hash-runtime-portfolio",
                created_at_utc=T0,
            )
        )
        conn.execute(
            store.tables["decision_lineage"].insert().values(
                firm_event_id="firm-runtime-portfolio",
                setup_id="setup-runtime-portfolio",
                ticket_id="ticket-runtime-portfolio",
                order_intent_id=None,
                trade_id=None,
                asset_id="btc",
                route_id="btc:daily_swing:long",
                playbook_id="pb_crypto_swing_v1_2",
                playbook_version="1.2",
                risk_cluster_id="crypto",
                asset_risk_hitches={},
                policy_version="policy-runtime-portfolio",
                configuration_hash="cfg-runtime-portfolio",
                market_observation_id=obs.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
                row_version=1,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-runtime-portfolio",
                exit_plan_id="exit-runtime-portfolio",
                setup_id="setup-runtime-portfolio",
                firm_event_id="firm-runtime-portfolio",
                asset_id="btc",
                route_id="btc:daily_swing:long",
                state="READY",
                signal_key="signal-runtime-portfolio",
                side="long",
                horizon="daily_swing",
                stop_price=95_000.0,
                quantity=0.01,
                modeled_round_trip_cost_pct=0.62,
                reject_code=None,
                policy_version="policy-runtime-portfolio",
                configuration_hash="cfg-runtime-portfolio",
                market_observation_id=obs.observation_id,
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
    return engine, store, obs


def _reserve(
    conn,
    store: VNextStore,
    obs: MarketObservation,
    *,
    order_intent_id: str = "intent-runtime-portfolio",
):
    return reserve_runtime_ready_ticket(
        conn,
        store,
        ticket_id="ticket-runtime-portfolio",
        order_intent_id=order_intent_id,
        current_observation=obs,
        current_observations={"btc": obs},
        created_at_utc=T0,
        event_id="evt-runtime-portfolio",
    )


def test_runtime_portfolio_bridge_reserves_ready_ticket_without_resizing() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        result = _reserve(conn, store, obs)
        intent = conn.execute(
            sa.select(store.tables["order_intents"]).where(
                store.tables["order_intents"].c.order_intent_id
                == "intent-runtime-portfolio"
            )
        ).mappings().one()
        reservation = conn.execute(
            sa.select(store.tables["risk_admission_reservations"])
        ).mappings().one()
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-portfolio",
        )

    assert result["ok"] is True
    assert result["state"] == "RESERVED"
    assert intent["requested_qty"] == pytest.approx(0.01)
    assert intent["broker_account_id"] == "kraken_paper"
    assert intent["broker"] == "Kraken"
    assert intent["venue"] == "Kraken"
    assert intent["symbol_executed"] == "BTC/USD"
    assert intent["position_key"] == "btc:daily_swing"
    assert intent["exit_plan_id"] == "exit-runtime-portfolio"
    assert intent["hard_stop_price"] == pytest.approx(95_000.0)
    assert intent["ready_spread_bps"] == pytest.approx(2.0)
    assert intent["idempotency_key"] == open_intent_idempotency_key(
        ticket_id="ticket-runtime-portfolio",
        side="long",
        quantity=0.01,
        asset_id="btc",
        horizon="daily_swing",
        signal_key="signal-runtime-portfolio",
    )
    assert reservation["order_intent_id"] == "intent-runtime-portfolio"
    assert reservation["stop_risk_usd"] > 0
    assert ticket is not None
    assert ticket.state.value == "READY"
    assert ticket.quantity == pytest.approx(0.01)


def test_runtime_portfolio_bridge_reuses_canonical_open_idempotency() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        first = _reserve(conn, store, obs)
        second = _reserve(
            conn,
            store,
            obs,
            order_intent_id="intent-runtime-portfolio-retry",
        )
        intent_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one()

    assert first["state"] == "RESERVED"
    assert second["duplicate"] is True
    assert second["order_intent_id"] == "intent-runtime-portfolio"
    assert intent_count == 1


def test_runtime_portfolio_bridge_fails_closed_without_runtime_binding() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        conn.execute(store.tables["product_registry_state"].delete())
        with pytest.raises(
            RuntimeError,
            match="runtime product binding missing",
        ):
            _reserve(conn, store, obs)
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one() == 0
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-portfolio",
        )

    assert ticket is not None
    assert ticket.state.value == "READY"
