"""Runtime bridge from FLATTEN_REQUEST to a zero-capital CLOSE reservation."""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.exit_plan import EXIT_PRECEDENCE, ExitReason
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.store import VNextStore


_ACTIVE_EXIT_REASONS = frozenset(EXIT_PRECEDENCE)


def reserve_runtime_flatten(
    conn: Connection,
    store: VNextStore,
    *,
    order_intent_id: str,
    trade_id: str,
    idempotency_key: str,
    exit_reason: ExitReason,
    market_observation_id: str,
    created_at_utc: datetime,
    event_id: str,
) -> dict[str, object]:
    """Reserve a paper CLOSE only after a matching durable FLATTEN_REQUEST."""
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    for name, value in (
        ("order_intent_id", order_intent_id),
        ("trade_id", trade_id),
        ("idempotency_key", idempotency_key),
        ("market_observation_id", market_observation_id),
        ("event_id", event_id),
    ):
        if not str(value).strip():
            raise ValueError(f"{name} is required")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("runtime close reservation safety invariant is not paper-only")

    try:
        reason = (
            exit_reason
            if isinstance(exit_reason, ExitReason)
            else ExitReason(str(exit_reason))
        )
    except ValueError as exc:
        raise ValueError("unknown runtime exit reason") from exc
    if reason not in _ACTIVE_EXIT_REASONS:
        raise ValueError("runtime exit reason is not an active EXIT_PRECEDENCE trigger")

    closed = store.tables["closed_trades"]
    if conn.execute(
        sa.select(closed.c.trade_id).where(closed.c.trade_id == trade_id)
    ).first() is not None:
        return store.reserve_flatten_intent(
            conn,
            order_intent_id=order_intent_id,
            trade_id=trade_id,
            idempotency_key=idempotency_key,
            exit_reason=reason.value,
            market_observation_id=market_observation_id,
            reference_price=None,
            ready_spread_bps=None,
            created_at_utc=created_at_utc,
            event_id=event_id,
            actor="Portfolio",
        )

    trades = store.tables["open_trades"]
    trade = conn.execute(
        sa.select(trades).where(trades.c.trade_id == trade_id)
    ).mappings().first()
    if trade is None:
        return {"ok": False, "error": "trade_not_open"}

    events = store.tables["event_ledger"]
    flatten_request = conn.execute(
        sa.select(events.c.event_id).where(
            sa.and_(
                events.c.aggregate_type == "trade",
                events.c.aggregate_id == trade_id,
                events.c.new_state == "FLATTEN_REQUEST",
                events.c.reason_code == reason.value,
            )
        )
    ).first()
    if flatten_request is None:
        raise RuntimeError("matching FLATTEN_REQUEST is required before CLOSE reserve")

    observation = store.load_market_observation(
        conn,
        observation_id=market_observation_id,
    )
    if observation is None:
        raise KeyError(
            f"unknown close-reserve market observation: {market_observation_id}"
        )
    if observation.asset_id != str(trade["asset_id"]):
        raise ValueError("close-reserve market observation asset mismatch")

    side = str(trade["side"]).strip().lower()
    reference_price = (
        observation.bid
        if side == "long"
        else observation.ask
        if side == "short"
        else None
    )
    if side not in {"long", "short"}:
        raise RuntimeError("open trade has invalid side")

    return store.reserve_flatten_intent(
        conn,
        order_intent_id=order_intent_id,
        trade_id=trade_id,
        idempotency_key=idempotency_key,
        exit_reason=reason.value,
        market_observation_id=market_observation_id,
        reference_price=reference_price,
        ready_spread_bps=observation.spread_bps,
        created_at_utc=created_at_utc,
        event_id=event_id,
        actor="Portfolio",
    )
