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
from aether_vnext.store import VNextStore, open_intent_idempotency_key


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 19, 30, tzinfo=UTC)


def _observation() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-eurusd",
        asset_id="eurusd",
        venue="paper",
        bid=1.0998,
        ask=1.1000,
        last=1.0999,
        mark=1.0999,
        source="paper-test",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=10,
        spread_abs=0.0002,
        spread_bps=(0.0002 / 1.0999) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="v1",
    )


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        store.record_market_observation(conn, _observation())
        conn.execute(
            store.tables["exit_plans"].insert().values(
                exit_plan_id="exit-eurusd",
                version="v1",
                hard_stop_price=1.0950,
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
                payload_hash="hash-exit-eurusd",
                created_at_utc=T0,
            )
        )
    return engine, store


def _ticket(
    conn,
    store: VNextStore,
    *,
    index: int,
    horizon: str,
    quantity: float = 0.10,
) -> dict[str, str]:
    ticket_id = f"ticket-{index}"
    signal_key = f"signal-{index}"
    route_id = f"eurusd:{horizon}:long"
    conn.execute(
        store.tables["tickets"].insert().values(
            ticket_id=ticket_id,
            exit_plan_id="exit-eurusd",
            setup_id=f"setup-{index}",
            firm_event_id=None,
            asset_id="eurusd",
            route_id=route_id,
            state="READY",
            signal_key=signal_key,
            side="long",
            horizon=horizon,
            stop_price=1.0950,
            quantity=quantity,
            modeled_round_trip_cost_pct=0.10,
            reject_code=None,
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id="obs-eurusd",
            first_killed_by=None,
            first_kill_reason=None,
            created_at_utc=T0,
        )
    )
    return {
        "ticket_id": ticket_id,
        "signal_key": signal_key,
        "route_id": route_id,
        "position_key": f"eurusd:{horizon}",
        "horizon": horizon,
    }


def _reserve(
    conn,
    store: VNextStore,
    *,
    spec: dict[str, str],
    quantity: float = 0.10,
):
    idem = open_intent_idempotency_key(
        ticket_id=spec["ticket_id"],
        side="long",
        quantity=quantity,
        asset_id="eurusd",
        horizon=spec["horizon"],
        signal_key=spec["signal_key"],
    )
    return store.reserve_risk_checked_open_intent(
        conn,
        order_intent_id=f"intent-{spec['ticket_id']}",
        ticket_id=spec["ticket_id"],
        firm_event_id=None,
        asset_id="eurusd",
        route_id=spec["route_id"],
        broker_account_id="tastyfx_paper",
        broker="tastyfx",
        venue="paper",
        symbol="EURUSD",
        side="long",
        qty=quantity,
        order_type="MARKET_PAPER",
        reference_price=None,
        expected_fill=None,
        idempotency_key=idem,
        signal_key=spec["signal_key"],
        position_key=spec["position_key"],
        reserve_cash_usd=None,
        reserve_margin_usd=None,
        ready_spread_bps=2.0,
        hard_stop_price=1.0950,
        exit_plan_id="exit-eurusd",
        submit_timeout_at=None,
        policy_version="policy-v1",
        configuration_hash="cfg",
        market_observation_id="obs-eurusd",
        created_at_utc=T0,
        event_id=f"evt-{spec['ticket_id']}",
        actor="portfolio",
        risk_cluster_id="fx",
        cluster_by_asset={"eurusd": "fx"},
        current_observations={},
    )


def test_atomic_pending_risk_prevents_asset_overbooking() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        first = _ticket(conn, store, index=1, horizon="scalp")
        second = _ticket(conn, store, index=2, horizon="intraday")
        third = _ticket(conn, store, index=3, horizon="swing")

        one = _reserve(conn, store, spec=first)
        two = _reserve(conn, store, spec=second)
        three = _reserve(conn, store, spec=third)

        assert one["state"] == "RESERVED"
        assert two["state"] == "RESERVED"
        assert one["reserved_stop_risk_usd"] > 0
        assert two["reserved_stop_risk_usd"] > 0

        assert three["ok"] is False
        assert three["reject_code"] == "asset_risk_full"
        assert three["state"] == "REJECTED"

        reservation_rows = conn.execute(
            sa.select(store.tables["risk_admission_reservations"])
        ).mappings().all()
        assert len(reservation_rows) == 2

        intent_rows = conn.execute(
            sa.select(store.tables["order_intents"])
        ).mappings().all()
        assert len(intent_rows) == 2

        ticket3 = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-3"
            )
        ).mappings().one()
        assert ticket3["first_killed_by"] == "Portfolio"
        assert ticket3["first_kill_reason"] == "asset_risk_full"


def test_pending_submitted_intent_still_consumes_risk_capacity() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        first = _ticket(conn, store, index=1, horizon="scalp")
        second = _ticket(conn, store, index=2, horizon="intraday")
        third = _ticket(conn, store, index=3, horizon="swing")
        one = _reserve(conn, store, spec=first)
        assert one["state"] == "RESERVED"
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-ticket-1",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=None,
            event_id="evt-submit-1",
            actor="paper-adapter",
        )
        assert _reserve(conn, store, spec=second)["state"] == "RESERVED"
        blocked = _reserve(conn, store, spec=third)
        assert blocked["reject_code"] == "asset_risk_full"


def test_per_trade_ceiling_cannot_be_bypassed_by_ready_ticket() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        spec = _ticket(
            conn,
            store,
            index=10,
            horizon="swing",
            quantity=0.20,
        )
        result = _reserve(
            conn,
            store,
            spec=spec,
            quantity=0.20,
        )
        assert result["ok"] is False
        assert result["reject_code"] == "ticket_contract_mismatch"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one() == 0


def test_missing_firm_guard_fails_closed_before_reservation() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        spec = _ticket(conn, store, index=20, horizon="swing")
        conn.execute(store.tables["risk_admission_guard"].delete())
        with pytest.raises(
            RuntimeError,
            match="Firm risk admission guard is not provisioned",
        ):
            _reserve(conn, store, spec=spec)
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one() == 0


def test_pending_open_without_risk_record_fails_closed() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        # Simulate an old/bypassed Phase-5 reservation that did not pass 6D.
        conn.execute(
            store.tables["order_intents"].insert().values(
                order_intent_id="legacy-pending",
                broker_account_id="tastyfx_paper",
                exit_plan_id="exit-eurusd",
                intent_kind="OPEN",
                exit_reason=None,
                position_key="eurusd:legacy",
                signal_key="legacy-signal",
                reserved_cash_usd=1.0,
                reserved_margin_usd=1.0,
                ready_spread_bps=2.0,
                hard_stop_price=1.0950,
                submit_timeout_at=T0,
                observation_id_at_fill=None,
                trade_id=None,
                version=1,
                ticket_id="legacy-ticket",
                firm_event_id=None,
                asset_id="eurusd",
                route_id="eurusd:legacy:long",
                broker="tastyfx",
                venue="paper",
                symbol_executed="EURUSD",
                side="long",
                requested_qty=0.01,
                order_type="MARKET_PAPER",
                reference_price=1.1,
                expected_fill_price=1.1,
                state="RESERVED",
                submitted_at=None,
                acknowledged_at=None,
                filled_at=None,
                filled_qty=0.0,
                avg_fill_price=None,
                reject_code=None,
                slip_usd=None,
                slip_bps=None,
                idempotency_key="legacy-idem",
                policy_version="policy-v1",
                configuration_hash="cfg",
                observation_id_at_reserve="obs-eurusd",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
        spec = _ticket(conn, store, index=30, horizon="swing")
        with pytest.raises(
            RuntimeError,
            match="pending OPEN intent missing atomic risk reservation",
        ):
            _reserve(conn, store, spec=spec)
