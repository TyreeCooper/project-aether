"""Runtime bridge from an evaluated Exit trigger to FLATTEN_REQUEST.

This module does not invent or evaluate structure, trailing, profit-taking, session,
stale-mark, or Governor policy. It accepts only one already-evaluated active exit
reason from the frozen EXIT_PRECEDENCE, validates durable trade/observation identity,
and delegates the no-cash OPEN -> FLATTEN_REQUEST event to VNextStore.
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.exit_plan import EXIT_PRECEDENCE, ExitReason
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.store import VNextStore


_ACTIVE_EXIT_REASONS = frozenset(EXIT_PRECEDENCE)


def request_runtime_flatten(
    conn: Connection,
    store: VNextStore,
    *,
    trade_id: str,
    exit_reason: ExitReason,
    market_observation_id: str,
    at_utc: datetime,
    event_id: str,
) -> dict[str, object]:
    """Persist one already-evaluated runtime Exit trigger as FLATTEN_REQUEST."""
    if at_utc.tzinfo is None:
        raise ValueError("at_utc must be timezone-aware")
    for name, value in (
        ("trade_id", trade_id),
        ("market_observation_id", market_observation_id),
        ("event_id", event_id),
    ):
        if not str(value).strip():
            raise ValueError(f"{name} is required")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("runtime exit safety invariant is not paper-only")

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
        return store.request_flatten(
            conn,
            trade_id=trade_id,
            exit_reason=reason.value,
            market_observation_id=market_observation_id,
            at_utc=at_utc,
            event_id=event_id,
            actor="Exit",
        )

    trades = store.tables["open_trades"]
    trade = conn.execute(
        sa.select(trades).where(trades.c.trade_id == trade_id)
    ).mappings().first()
    if trade is None:
        return {"ok": False, "error": "trade_not_open"}

    observation = store.load_market_observation(
        conn,
        observation_id=market_observation_id,
    )
    if observation is None:
        raise KeyError(
            f"unknown exit market observation: {market_observation_id}"
        )
    if observation.asset_id != str(trade["asset_id"]):
        raise ValueError("exit market observation asset mismatch")

    return store.request_flatten(
        conn,
        trade_id=trade_id,
        exit_reason=reason.value,
        market_observation_id=market_observation_id,
        at_utc=at_utc,
        event_id=event_id,
        actor="Exit",
    )
