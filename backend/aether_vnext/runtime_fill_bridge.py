"""Runtime bridge from SUBMITTED paper OPEN intents to durable OPEN trades.

All execution math remains in execution.py and all durable book mutation remains in
VNextStore. This bridge only validates runtime binding continuity, applies the paper
fill decision, and routes either a zero-fill rejection or an all-or-none fill into
the existing atomic Store contracts.
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.domain import OrderIntentState
from aether_vnext.execution import fill_submitted_paper_intent
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.registry_runtime import materialize_bound_registry_row
from aether_vnext.risk import stop_risk_usd
from aether_vnext.store import VNextStore


_TERMINAL = frozenset(
    {
        OrderIntentState.FILLED,
        OrderIntentState.REJECTED,
        OrderIntentState.CANCELLED,
        OrderIntentState.CANCELLED_STALE,
    }
)


def fill_runtime_submitted_open(
    conn: Connection,
    store: VNextStore,
    *,
    order_intent_id: str,
    trade_id: str,
    fill_market_observation_id: str,
    filled_at_utc: datetime,
    event_id: str,
) -> dict[str, object]:
    """Apply one paper fill-time decision and persist its durable result."""
    if filled_at_utc.tzinfo is None:
        raise ValueError("filled_at_utc must be timezone-aware")
    for name, value in (
        ("order_intent_id", order_intent_id),
        ("trade_id", trade_id),
        ("fill_market_observation_id", fill_market_observation_id),
        ("event_id", event_id),
    ):
        if not str(value).strip():
            raise ValueError(f"{name} is required")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("runtime execution safety invariant is not paper-only")

    intent = store.load_order_intent(
        conn,
        order_intent_id=order_intent_id,
    )
    if intent is None:
        raise KeyError(f"unknown order intent: {order_intent_id}")
    if intent.intent_kind != "OPEN":
        raise ValueError("runtime OPEN fill bridge requires OPEN intent")
    if intent.order_type != "MARKET_PAPER":
        raise RuntimeError("runtime OPEN fill bridge requires MARKET_PAPER")

    if intent.state in _TERMINAL:
        return {
            "ok": True,
            "duplicate": True,
            "state": intent.state.value,
            "trade_id": intent.trade_id,
        }
    if intent.state is not OrderIntentState.SUBMITTED:
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
            "SUBMITTED OPEN intent missing atomic Firm risk reservation"
        )

    observation = store.load_market_observation(
        conn,
        observation_id=fill_market_observation_id,
    )
    if observation is None:
        raise KeyError(
            f"unknown fill market observation: {fill_market_observation_id}"
        )
    asset_id = str(intent.lineage.asset_id).strip().lower()
    if observation.asset_id != asset_id:
        raise ValueError("fill market observation asset mismatch")

    runtime = store.load_runtime_registry_binding(conn, asset_id=asset_id)
    if runtime is None:
        raise RuntimeError("SUBMITTED intent runtime product binding missing")
    if runtime["configuration_hash"] != intent.lineage.configuration_hash:
        raise RuntimeError(
            "SUBMITTED intent runtime product binding configuration mismatch"
        )
    bound_row = materialize_bound_registry_row(
        runtime["binding"],
        as_of_utc=filled_at_utc,
    )
    if (
        intent.broker != bound_row.broker
        or intent.venue != bound_row.venue
        or intent.symbol_executed != bound_row.broker_symbol
    ):
        raise RuntimeError("SUBMITTED intent runtime routing drift")
    if bound_row.stale_threshold_ms is None:
        raise RuntimeError("runtime product binding stale threshold missing")
    if intent.ready_spread_bps is None:
        raise RuntimeError("SUBMITTED intent missing READY spread baseline")
    if intent.hard_stop_price is None:
        raise RuntimeError("SUBMITTED intent missing hard stop")

    transition = fill_submitted_paper_intent(
        intent,
        observation=observation,
        registry_row=bound_row,
        ready_spread_bps=float(intent.ready_spread_bps),
        hard_stop_price=float(intent.hard_stop_price),
        max_age_ms=int(bound_row.stale_threshold_ms),
        at_utc=filled_at_utc,
    )
    if not transition.applied:
        return {
            "ok": False,
            "duplicate": False,
            "state": intent.state.value,
            "reason": transition.reason,
        }

    decided = transition.intent
    if decided.state is OrderIntentState.REJECTED:
        reject_code = str(decided.reject_code or transition.reason).strip()
        return store.release_order_reservation(
            conn,
            order_intent_id=order_intent_id,
            terminal_state=OrderIntentState.REJECTED.value,
            reject_code=reject_code,
            at_utc=filled_at_utc,
            event_id=event_id,
            actor="paper-adapter",
            first_killed_by="execution",
            fill_market_observation_id=fill_market_observation_id,
        )
    if decided.state is not OrderIntentState.FILLED:
        raise RuntimeError(
            f"unexpected paper fill transition state: {decided.state.value}"
        )
    if (
        decided.filled_at is None
        or decided.avg_fill_price is None
        or decided.slip_usd is None
        or decided.slip_bps is None
    ):
        raise RuntimeError("paper fill transition missing fill economics")

    ticket_id = str(intent.lineage.ticket_id or "").strip()
    if not ticket_id:
        raise RuntimeError("SUBMITTED OPEN intent missing ticket identity")
    ticket = store.load_ticket(conn, ticket_id=ticket_id)
    if ticket is None:
        raise RuntimeError("SUBMITTED OPEN intent ticket missing")
    setup_id = str(ticket.lineage.setup_id or "").strip()
    if not setup_id:
        raise RuntimeError("SUBMITTED OPEN intent missing setup identity")
    exit_plan_id = str(ticket.exit_plan_id or "").strip()
    if not exit_plan_id:
        raise RuntimeError("SUBMITTED OPEN intent ticket missing ExitPlan")

    initial_stop_risk = stop_risk_usd(
        bound_row,
        side=intent.side,
        quantity=float(decided.filled_qty),
        entry_price=float(decided.avg_fill_price),
        stop_price=float(intent.hard_stop_price),
    )
    return store.finalize_filled_open(
        conn,
        order_intent_id=order_intent_id,
        trade_id=trade_id,
        setup_id=setup_id,
        exit_plan_id=exit_plan_id,
        fill_market_observation_id=fill_market_observation_id,
        filled_at_utc=decided.filled_at,
        filled_qty=float(decided.filled_qty),
        avg_fill_price=float(decided.avg_fill_price),
        slippage_usd=float(decided.slip_usd),
        slippage_bps=float(decided.slip_bps),
        initial_stop_risk_usd=initial_stop_risk,
        management_telemetry={},
        event_id=event_id,
        actor="paper-adapter",
    )
