from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.exit_plan import ExitReason
from aether_vnext.reconciler import reconcile_stale_intents
from aether_vnext.restart import load_restart_snapshot
from aether_vnext.runtime_close_execution_bridge import (
    submit_runtime_reserved_close,
)
from aether_vnext.runtime_close_reserve_bridge import reserve_runtime_flatten
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_portfolio_bridge import reserve_runtime_ready_ticket
from tests_vnext.test_runtime_close_reserve_bridge import _open_and_request
from tests_vnext.test_runtime_portfolio_bridge import T0, _fixture


def _ledger(conn, store):
    return conn.execute(
        sa.select(store.tables["broker_account_ledgers"]).where(
            store.tables["broker_account_ledgers"].c.broker_account_id
            == "kraken_paper"
        )
    ).mappings().one()


def _count(conn, table) -> int:
    return int(
        conn.execute(
            sa.select(sa.func.count()).select_from(table)
        ).scalar_one()
    )


def test_reconciler_cancels_stale_open_once_and_releases_all_pending_risk() -> None:
    engine, store, obs = _fixture()
    intent_id = "intent-runtime-stale-open"

    with engine.begin() as conn:
        starting = _ledger(conn, store)

        reserved = reserve_runtime_ready_ticket(
            conn,
            store,
            ticket_id="ticket-runtime-portfolio",
            order_intent_id=intent_id,
            current_observation=obs,
            current_observations={"btc": obs},
            created_at_utc=T0,
            event_id="evt-runtime-stale-open-reserve",
        )
        assert reserved["state"] == "RESERVED"

        submitted = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id=intent_id,
            submitted_at_utc=T0,
            event_id="evt-runtime-stale-open-submit",
        )
        assert submitted["state"] == "SUBMITTED"

        intent = store.load_order_intent(conn, order_intent_id=intent_id)
        assert intent is not None
        assert intent.submit_timeout_at == T0 + timedelta(seconds=15)

        assert reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=15),
        ) == ()

        before_stale = load_restart_snapshot(conn, store=store)
        assert tuple(
            row["order_intent_id"]
            for row in before_stale.in_flight_order_intents
        ) == (intent_id,)
        assert tuple(
            row["order_intent_id"]
            for row in before_stale.risk_admission_reservations
        ) == (intent_id,)
        assert before_stale.risk_admission_issues == ()

        first = reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=15, milliseconds=1),
        )
        assert len(first) == 1
        assert first[0]["state"] == "CANCELLED_STALE"
        assert first[0]["duplicate"] is False

        terminal = store.load_order_intent(conn, order_intent_id=intent_id)
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-portfolio",
        )
        assert terminal is not None
        assert terminal.state.value == "CANCELLED_STALE"
        assert terminal.reject_code == "submit_timeout"
        assert terminal.first_killed_by == "Portfolio"
        assert terminal.first_kill_reason == "submit_timeout"
        assert ticket is not None
        assert ticket.state.value == "REJECTED"
        assert ticket.first_killed_by == "Portfolio"
        assert ticket.first_kill_reason == "submit_timeout"

        assert _count(conn, store.tables["risk_admission_reservations"]) == 0
        assert _count(conn, store.tables["active_positions"]) == 0
        assert _count(conn, store.tables["open_trades"]) == 0
        assert _count(conn, store.tables["signal_consumptions"]) == 0
        assert store.risk_admission_reconciliation_issues(conn) == ()

        restored = _ledger(conn, store)
        assert restored["cash_available_usd"] == pytest.approx(
            starting["cash_available_usd"]
        )
        assert restored["cash_reserved_usd"] == pytest.approx(
            starting["cash_reserved_usd"]
        )
        assert restored["margin_used_usd"] == pytest.approx(
            starting["margin_used_usd"]
        )
        assert restored["margin_available_usd"] == pytest.approx(
            starting["margin_available_usd"]
        )

        event_count = _count(conn, store.tables["event_ledger"])
        second = reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=30),
        )
        assert second == ()
        assert _count(conn, store.tables["event_ledger"]) == event_count

        after_restart = load_restart_snapshot(conn, store=store)
        assert after_restart.in_flight_order_intents == ()
        assert after_restart.risk_admission_reservations == ()
        assert after_restart.risk_admission_issues == ()


def test_reconciler_cancels_stale_close_without_releasing_open_position() -> None:
    engine, store, obs = _fixture()
    close_intent_id = "intent-runtime-stale-close"

    with engine.begin() as conn:
        observation_id = _open_and_request(conn, store, obs)
        open_ledger = _ledger(conn, store)

        reserved = reserve_runtime_flatten(
            conn,
            store,
            order_intent_id=close_intent_id,
            trade_id="trade-runtime-close",
            idempotency_key="idem-runtime-stale-close",
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=observation_id,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-stale-close-reserve",
        )
        assert reserved["state"] == "RESERVED"

        submitted = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            submitted_at_utc=T0 + timedelta(seconds=2),
            event_id="evt-runtime-stale-close-submit",
        )
        assert submitted["state"] == "SUBMITTED"

        close_intent = store.load_order_intent(
            conn,
            order_intent_id=close_intent_id,
        )
        assert close_intent is not None
        assert close_intent.submit_timeout_at == T0 + timedelta(seconds=16)

        first = reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=16, milliseconds=1),
        )
        assert len(first) == 1
        assert first[0]["state"] == "CANCELLED_STALE"

        terminal = store.load_order_intent(
            conn,
            order_intent_id=close_intent_id,
        )
        assert terminal is not None
        assert terminal.state.value == "CANCELLED_STALE"
        assert terminal.reject_code == "submit_timeout"

        assert _count(conn, store.tables["active_positions"]) == 1
        assert _count(conn, store.tables["open_trades"]) == 1
        assert _count(conn, store.tables["closed_trades"]) == 0
        assert _count(conn, store.tables["signal_consumptions"]) == 1
        assert _count(conn, store.tables["risk_admission_reservations"]) == 0
        assert store.risk_admission_reconciliation_issues(conn) == ()

        after = _ledger(conn, store)
        assert after["cash_available_usd"] == pytest.approx(
            open_ledger["cash_available_usd"]
        )
        assert after["cash_reserved_usd"] == pytest.approx(
            open_ledger["cash_reserved_usd"]
        )
        assert after["margin_used_usd"] == pytest.approx(
            open_ledger["margin_used_usd"]
        )
        assert after["margin_available_usd"] == pytest.approx(
            open_ledger["margin_available_usd"]
        )

        event_count = _count(conn, store.tables["event_ledger"])
        second = reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=30),
        )
        assert second == ()
        assert _count(conn, store.tables["event_ledger"]) == event_count

        restart = load_restart_snapshot(conn, store=store)
        assert restart.in_flight_order_intents == ()
        assert tuple(
            row["trade_id"] for row in restart.active_positions
        ) == ("trade-runtime-close",)
        assert tuple(
            row["trade_id"] for row in restart.open_trade_records
        ) == ("trade-runtime-close",)
