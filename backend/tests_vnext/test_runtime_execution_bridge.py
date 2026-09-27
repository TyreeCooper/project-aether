from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 8, 45, tzinfo=UTC)


def _fixture() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["order_intents"].insert().values(
                order_intent_id="intent-runtime-submit",
                broker_account_id="kraken_paper",
                exit_plan_id="exit-runtime-submit",
                intent_kind="OPEN",
                exit_reason=None,
                position_key="btc:daily_swing",
                signal_key="signal-runtime-submit",
                reserved_cash_usd=1_100.0,
                reserved_margin_usd=0.0,
                ready_spread_bps=2.0,
                hard_stop_price=95_000.0,
                submit_timeout_at=T0 + timedelta(seconds=15),
                shortability_evidence_id=None,
                observation_id_at_fill=None,
                trade_id=None,
                version=1,
                ticket_id="ticket-runtime-submit",
                firm_event_id="firm-runtime-submit",
                asset_id="btc",
                route_id="btc:daily_swing:long",
                broker="Kraken",
                venue="Kraken",
                symbol_executed="BTC/USD",
                side="long",
                requested_qty=0.01,
                order_type="MARKET_PAPER",
                reference_price=100_010.0,
                expected_fill_price=100_060.005,
                state="RESERVED",
                submitted_at=None,
                acknowledged_at=None,
                filled_at=None,
                filled_qty=0.0,
                avg_fill_price=None,
                reject_code=None,
                slip_usd=None,
                slip_bps=None,
                idempotency_key="idem-runtime-submit",
                policy_version="policy-runtime-submit",
                configuration_hash="cfg-runtime-submit",
                observation_id_at_reserve="obs-runtime-submit",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
        conn.execute(
            store.tables["risk_admission_reservations"].insert().values(
                order_intent_id="intent-runtime-submit",
                asset_id="btc",
                cluster_id="crypto",
                stop_risk_usd=50.0,
                policy_version="policy-runtime-submit",
                configuration_hash="cfg-runtime-submit",
                created_at_utc=T0,
            )
        )
    return engine, store


def test_runtime_execution_bridge_submits_reserved_open_without_filling() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        result = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id="intent-runtime-submit",
            submitted_at_utc=T0,
            event_id="evt-runtime-submit",
        )
        intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-submit",
        )
        event_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["event_ledger"]
            )
        ).scalar_one()

    assert result["ok"] is True
    assert result["state"] == "SUBMITTED"
    assert intent is not None
    assert intent.state.value == "SUBMITTED"
    assert intent.submitted_at == T0
    assert intent.acknowledged_at == T0
    assert intent.filled_at is None
    assert intent.filled_qty == 0.0
    assert intent.avg_fill_price is None
    assert intent.submit_timeout_at == T0 + timedelta(seconds=15)
    assert event_count == 1


def test_runtime_execution_bridge_submit_retry_is_idempotent() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        first = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id="intent-runtime-submit",
            submitted_at_utc=T0,
            event_id="evt-runtime-submit",
        )
        second = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id="intent-runtime-submit",
            submitted_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-submit-retry",
        )
        event_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["event_ledger"]
            )
        ).scalar_one()

    assert first["state"] == "SUBMITTED"
    assert second == {
        "ok": True,
        "duplicate": True,
        "state": "SUBMITTED",
    }
    assert event_count == 1


def test_runtime_execution_bridge_refuses_untracked_open_reservation() -> None:
    engine, store = _fixture()
    with engine.begin() as conn:
        conn.execute(store.tables["risk_admission_reservations"].delete())
        with pytest.raises(
            RuntimeError,
            match="missing atomic Firm risk reservation",
        ):
            submit_runtime_reserved_open(
                conn,
                store,
                order_intent_id="intent-runtime-submit",
                submitted_at_utc=T0,
                event_id="evt-runtime-submit-untracked",
            )
        intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-submit",
        )

    assert intent is not None
    assert intent.state.value == "RESERVED"
    assert intent.submitted_at is None
