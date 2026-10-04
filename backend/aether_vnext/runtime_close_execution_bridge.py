"""Runtime bridge from a RESERVED paper CLOSE intent to SUBMITTED."""
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


def submit_runtime_reserved_close(
    conn: Connection,
    store: VNextStore,
    *,
    order_intent_id: str,
    submitted_at_utc: datetime,
    event_id: str,
) -> dict[str, object]:
    """Submit one durable risk-reducing paper CLOSE intent."""
    if submitted_at_utc.tzinfo is None:
        raise ValueError("submitted_at_utc must be timezone-aware")
    if not str(order_intent_id).strip():
        raise ValueError("order_intent_id is required")
    if not str(event_id).strip():
        raise ValueError("event_id is required")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("runtime close execution safety invariant is not paper-only")

    intent = store.load_order_intent(
        conn,
        order_intent_id=order_intent_id,
    )
    if intent is None:
        raise KeyError(f"unknown order intent: {order_intent_id}")
    if intent.intent_kind != "CLOSE":
        raise ValueError("runtime CLOSE submit bridge requires CLOSE intent")
    if intent.order_type != "MARKET_PAPER":
        raise RuntimeError("runtime CLOSE submit bridge requires MARKET_PAPER")
    if (
        abs(float(intent.reserved_cash_usd)) > 1e-12
        or abs(float(intent.reserved_margin_usd)) > 1e-12
    ):
        raise RuntimeError("risk-reducing CLOSE intent may not reserve new capital")

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

    trade_id = str(intent.trade_id or "").strip()
    position_key = str(intent.position_key or "").strip()
    if not trade_id or not position_key:
        raise RuntimeError("CLOSE intent missing open-trade identity")

    trades = store.tables["open_trades"]
    trade = conn.execute(
        sa.select(trades.c.trade_id, trades.c.position_key).where(
            trades.c.trade_id == trade_id
        )
    ).first()
    if trade is None or str(trade.position_key) != position_key:
        raise RuntimeError("CLOSE intent no longer maps to an open trade")

    positions = store.tables["active_positions"]
    active = conn.execute(
        sa.select(positions.c.trade_id).where(
            positions.c.position_key == position_key
        )
    ).first()
    if active is None or str(active[0]) != trade_id:
        raise RuntimeError("CLOSE intent no longer maps to active position")

    transition = submit_paper_intent(
        intent,
        at_utc=submitted_at_utc,
    )
    if not transition.applied:
        raise RuntimeError(
            f"paper close submit transition refused RESERVED intent: {transition.reason}"
        )
    submitted = transition.intent
    if submitted.submitted_at is None or submitted.acknowledged_at is None:
        raise RuntimeError("paper close submit transition missing timestamps")

    return store.mark_order_intent_submitted(
        conn,
        order_intent_id=order_intent_id,
        submitted_at_utc=submitted.submitted_at,
        acknowledged_at_utc=submitted.acknowledged_at,
        submit_timeout_at=None,
        event_id=event_id,
        actor="paper-adapter",
    )
