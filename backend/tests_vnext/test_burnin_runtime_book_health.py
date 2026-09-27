from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from aether_vnext.burnin_readiness import (
    blocker_class,
    runtime_book_blockers,
)
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_portfolio_bridge import reserve_runtime_ready_ticket
from tests_vnext.test_runtime_portfolio_bridge import T0, _fixture


def _reserve_and_submit(conn, store, obs, *, intent_id: str) -> None:
    reserved = reserve_runtime_ready_ticket(
        conn,
        store,
        ticket_id="ticket-runtime-portfolio",
        order_intent_id=intent_id,
        current_observation=obs,
        current_observations={"btc": obs},
        created_at_utc=T0,
        event_id=f"evt-{intent_id}-reserve",
    )
    assert reserved["state"] == "RESERVED"
    submitted = submit_runtime_reserved_open(
        conn,
        store,
        order_intent_id=intent_id,
        submitted_at_utc=T0,
        event_id=f"evt-{intent_id}-submit",
    )
    assert submitted["state"] == "SUBMITTED"


def test_runtime_book_blockers_fail_closed_on_stale_pending_intent() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        _reserve_and_submit(
            conn,
            store,
            obs,
            intent_id="intent-burnin-stale",
        )

        assert runtime_book_blockers(
            conn,
            store=store,
            as_of_utc=T0 + timedelta(seconds=15),
        ) == ()

        blockers = runtime_book_blockers(
            conn,
            store=store,
            as_of_utc=T0 + timedelta(seconds=15, milliseconds=1),
        )

    assert blockers == ("stale_order_intents_present",)
    assert blocker_class(blockers[0]) == "runtime_reconciliation"


def test_runtime_book_blockers_surface_risk_reconciliation_defect() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        _reserve_and_submit(
            conn,
            store,
            obs,
            intent_id="intent-burnin-risk-drift",
        )
        conn.execute(
            store.tables["risk_admission_reservations"].delete().where(
                store.tables["risk_admission_reservations"].c.order_intent_id
                == "intent-burnin-risk-drift"
            )
        )

        blockers = runtime_book_blockers(
            conn,
            store=store,
            as_of_utc=T0 + timedelta(seconds=1),
        )

    assert blockers == (
        "risk_admission_reconciliation:"
        "missing_pending_risk_reservation:intent-burnin-risk-drift",
    )
    assert blocker_class(blockers[0]) == "runtime_reconciliation"
