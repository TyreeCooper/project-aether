"""Runtime bridge from durable RESERVED OPEN intents to paper SUBMITTED.

The bridge reuses the pure paper execution transition and the durable Store write.
It never talks to a live venue, never creates a fill, and refuses to submit an OPEN
intent that lacks the atomic Firm risk reservation created by Portfolio.
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.domain import OrderIntentState
from aether_vnext.execution import submit_paper_intent
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.store import VNextStore


_TERMINAL = frozenset(
    {
        OrderIntentState.FILLED,
        OrderIntentState.REJECTED,
        OrderIntentState.CANCELLED,
        OrderIntentState.CANCELLED_STALE,
    }
)


def submit_runtime_reserved_open(
    conn: Connection,
    store: VNextStore,
    *,
    order_intent_id: str,
    submitted_at_utc: datetime,
    event_id: str,
) -> dict[str, object]:
    """Persist RESERVED -> SUBMITTED for one paper OPEN intent."""
    if submitted_at_utc.tzinfo is None:
        raise ValueError("submitted_at_utc must be timezone-aware")
    if not str(order_intent_id).strip():
        raise ValueError("order_intent_id is required")
    if not str(event_id).strip():
        raise ValueError("event_id is required")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("runtime execution safety invariant is not paper-only")

    intent = store.load_order_intent(
        conn,
        order_intent_id=order_intent_id,
    )
    if intent is None:
        raise KeyError(f"unknown order intent: {order_intent_id}")
    if intent.intent_kind != "OPEN":
        raise ValueError("runtime OPEN submit bridge requires OPEN intent")
    if intent.order_type != "MARKET_PAPER":
        raise RuntimeError("runtime OPEN submit bridge requires MARKET_PAPER")

    if intent.state is OrderIntentState.SUBMITTED:
        return {
            "ok": True,
            "duplicate": True,
            "state": OrderIntentState.SUBMITTED.value,
        }
    if intent.state in _TERMINAL:
        return {
            "ok": False,
            "duplicate": False,
            "state": intent.state.value,
            "error": "terminal_state",
        }
    if intent.state is not OrderIntentState.RESERVED:
        return {
            "ok": False,
            "duplicate": False,
            "state": intent.state.value,
            "error": "illegal_state",
        }

    risk_reservations = store.tables["risk_admission_reservations"]
    tracked = conn.execute(
        sa.select(risk_reservations.c.order_intent_id).where(
            risk_reservations.c.order_intent_id == order_intent_id
        )
    ).first()
    if tracked is None:
        raise RuntimeError(
            "RESERVED OPEN intent missing atomic Firm risk reservation"
        )

    transition = submit_paper_intent(
        intent,
        at_utc=submitted_at_utc,
    )
    if not transition.applied:
        raise RuntimeError(
            f"paper submit transition refused RESERVED intent: {transition.reason}"
        )
    submitted = transition.intent
    if submitted.submitted_at is None or submitted.acknowledged_at is None:
        raise RuntimeError("paper submit transition missing timestamps")

    return store.mark_order_intent_submitted(
        conn,
        order_intent_id=order_intent_id,
        submitted_at_utc=submitted.submitted_at,
        acknowledged_at_utc=submitted.acknowledged_at,
        submit_timeout_at=None,
        event_id=event_id,
        actor="paper-adapter",
    )
