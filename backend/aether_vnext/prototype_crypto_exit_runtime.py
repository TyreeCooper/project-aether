"""Crash-resumable Kraken crypto PAPER close state machine.

This layer consumes the source-ordered crypto Exit decision and composes the
existing Exit -> Portfolio -> paper submit -> paper fill bridges. It never talks
to a live venue. A newly submitted CLOSE is never filled in the same pass; a later
supervisor cycle must satisfy paper latency with a fresh market observation.

Rejected stale/changed close attempts do not strand an OPEN trade: a future market
observation may create a new deterministic retry while the original attempt remains
immutable evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.domain import MarketObservation, OrderIntentState
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.prototype_crypto_exit import evaluate_prototype_crypto_exit
from aether_vnext.prototype_market_history import PrototypeMarketBar
from aether_vnext.runtime_close_execution_bridge import submit_runtime_reserved_close
from aether_vnext.runtime_close_fill_bridge import fill_runtime_submitted_close
from aether_vnext.runtime_close_reserve_bridge import reserve_runtime_flatten
from aether_vnext.runtime_exit_request_bridge import request_runtime_flatten
from aether_vnext.runtime_product_policy import (
    resolve_runtime_product,
    runtime_playbook_for_product,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
_PENDING_CLOSE_STATES = ("RESERVED", "SUBMITTED")


@dataclass(frozen=True, slots=True)
class PrototypeExitAdvanceResult:
    trade_id: str
    stage: str
    reason: str
    exit_reason: str | None
    order_intent_id: str | None


def _stored_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _close_identity(
    *,
    trade_id: str,
    exit_reason: str,
    market_observation_id: str,
) -> tuple[str, str, str]:
    raw = f"{trade_id}|{exit_reason}|{market_observation_id}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return (
        f"close-prototype-{digest}",
        f"prototype-close:{digest}",
        digest,
    )


def _pending_close(
    conn: Connection,
    store: VNextStore,
    *,
    trade_id: str,
):
    table = store.tables["order_intents"]
    return conn.execute(
        sa.select(table)
        .where(
            table.c.trade_id == trade_id,
            table.c.intent_kind == "CLOSE",
            table.c.state.in_(_PENDING_CLOSE_STATES),
        )
        .order_by(table.c.created_at_utc.asc())
        .limit(1)
    ).mappings().first()


def _advance_pending_close(
    conn: Connection,
    store: VNextStore,
    *,
    trade_id: str,
    pending,
    current_observation: MarketObservation,
    as_of_utc: datetime,
) -> PrototypeExitAdvanceResult:
    order_intent_id = str(pending["order_intent_id"])
    exit_reason = str(pending["exit_reason"] or "")

    if str(pending["state"]) == OrderIntentState.RESERVED.value:
        submitted = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id=order_intent_id,
            submitted_at_utc=as_of_utc,
            event_id=f"evt-prototype-close-submit-{hashlib.sha256(order_intent_id.encode()).hexdigest()[:24]}",
        )
        if submitted.get("state") != OrderIntentState.SUBMITTED.value:
            return PrototypeExitAdvanceResult(
                trade_id,
                "OPEN",
                str(submitted.get("error") or "close_submit_rejected"),
                exit_reason or None,
                order_intent_id,
            )
        return PrototypeExitAdvanceResult(
            trade_id,
            "CLOSE_SUBMITTED",
            "paper_latency_wait",
            exit_reason or None,
            order_intent_id,
        )

    if str(pending["state"]) != OrderIntentState.SUBMITTED.value:
        raise RuntimeError("unexpected pending CLOSE state")

    result = fill_runtime_submitted_close(
        conn,
        store,
        order_intent_id=order_intent_id,
        fill_market_observation_id=current_observation.observation_id,
        filled_at_utc=as_of_utc,
        event_id=f"evt-prototype-close-fill-{hashlib.sha256((order_intent_id + current_observation.observation_id).encode()).hexdigest()[:24]}",
    )
    state = str(result.get("state") or "")
    if state == "FLAT":
        return PrototypeExitAdvanceResult(
            trade_id,
            "FLAT",
            "paper_close_filled",
            exit_reason or None,
            order_intent_id,
        )
    if state == OrderIntentState.SUBMITTED.value:
        return PrototypeExitAdvanceResult(
            trade_id,
            "CLOSE_SUBMITTED",
            str(result.get("reason") or "paper_latency_wait"),
            exit_reason or None,
            order_intent_id,
        )
    if state == OrderIntentState.REJECTED.value:
        # The OPEN trade remains active. A later observation may create a fresh
        # deterministic close attempt.
        return PrototypeExitAdvanceResult(
            trade_id,
            "OPEN",
            str(result.get("reject_code") or result.get("error") or "close_rejected"),
            exit_reason or None,
            order_intent_id,
        )
    return PrototypeExitAdvanceResult(
        trade_id,
        "OPEN",
        str(result.get("reason") or result.get("error") or state or "close_pending"),
        exit_reason or None,
        order_intent_id,
    )


def advance_prototype_crypto_exit(
    conn: Connection,
    store: VNextStore,
    *,
    trade_id: str,
    current_observation: MarketObservation,
    latest_completed_hourly_bar: PrototypeMarketBar | None,
    as_of_utc: datetime,
    desk_scope_id: str | None = None,
) -> PrototypeExitAdvanceResult:
    """Advance one active verified Kraken crypto PAPER trade toward FLAT."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype exit requires PAPER_ONLY/LIVE_BLOCKED")
    trade_id = str(trade_id).strip()
    if not trade_id:
        raise ValueError("trade_id is required")

    closed = store.tables["closed_trades"]
    if conn.execute(
        sa.select(closed.c.trade_id).where(closed.c.trade_id == trade_id)
    ).first() is not None:
        return PrototypeExitAdvanceResult(
            trade_id, "FLAT", "already_flat", None, None
        )

    trades = store.tables["open_trades"]
    trade = conn.execute(
        sa.select(trades).where(trades.c.trade_id == trade_id)
    ).mappings().first()
    if trade is None:
        raise KeyError(f"unknown OPEN trade: {trade_id}")

    asset_id = str(trade["asset_id"]).strip().lower()
    if not asset_id:
        raise RuntimeError("OPEN trade missing asset identity")
    resolved = resolve_runtime_product(
        conn,
        store,
        asset_id=asset_id,
        as_of_utc=as_of_utc,
    )
    runtime_playbook_for_product(
        resolved.product,
        playbook_id="pb_crypto_swing_v1_2",
    )
    if current_observation.asset_id != asset_id:
        raise ValueError("current observation asset mismatch")

    active = store.tables["active_positions"]
    active_row = conn.execute(
        sa.select(active.c.trade_id).where(
            active.c.position_key == str(trade["position_key"])
        )
    ).first()
    if active_row is None or str(active_row[0]) != trade_id:
        raise RuntimeError("OPEN trade is not the active position")

    # Always finish an already-reserved/submitted risk-reducing close before
    # evaluating a new close attempt.
    pending = _pending_close(conn, store, trade_id=trade_id)
    if pending is not None:
        return _advance_pending_close(
            conn,
            store,
            trade_id=trade_id,
            pending=pending,
            current_observation=current_observation,
            as_of_utc=as_of_utc,
        )

    setup = store.load_setup(conn, setup_id=str(trade["setup_id"]))
    if setup is None or setup.invalidation is None:
        raise RuntimeError("OPEN crypto trade missing frozen breakout invalidation")

    governor = store.governor_block_for_admission(
        conn,
        route_id=str(trade["route_id"]),
        venue=current_observation.venue,
        product_id=asset_id,
        desk_scope_id=desk_scope_id,
    )
    decision = evaluate_prototype_crypto_exit(
        asset_id=asset_id,
        side=str(trade["side"]),
        opened_at_utc=_stored_utc(trade["opened_at_utc"]),
        exit_plan_payload=dict(trade["exit_plan_payload"] or {}),
        frozen_breakout_level=float(setup.invalidation),
        current_observation=current_observation,
        latest_completed_hourly_bar=latest_completed_hourly_bar,
        governor_halted=governor is not None,
        as_of_utc=as_of_utc,
    )
    if not decision.should_flatten or decision.exit_reason is None:
        return PrototypeExitAdvanceResult(
            trade_id,
            "OPEN",
            decision.reason,
            None,
            None,
        )

    reason = decision.exit_reason
    order_intent_id, idempotency_key, digest = _close_identity(
        trade_id=trade_id,
        exit_reason=reason.value,
        market_observation_id=current_observation.observation_id,
    )

    # If this exact market observation already produced a terminal rejected
    # close attempt, do not replay its immutable event IDs. Wait for new data.
    existing = store.load_order_intent(
        conn,
        order_intent_id=order_intent_id,
    )
    if existing is not None and existing.state in {
        OrderIntentState.REJECTED,
        OrderIntentState.CANCELLED,
        OrderIntentState.CANCELLED_STALE,
    }:
        return PrototypeExitAdvanceResult(
            trade_id,
            "OPEN",
            "await_new_market_observation_after_close_rejection",
            reason.value,
            order_intent_id,
        )

    request_runtime_flatten(
        conn,
        store,
        trade_id=trade_id,
        exit_reason=reason,
        market_observation_id=current_observation.observation_id,
        at_utc=as_of_utc,
        event_id=f"evt-prototype-flatten-{digest}",
    )
    reserve = reserve_runtime_flatten(
        conn,
        store,
        order_intent_id=order_intent_id,
        trade_id=trade_id,
        idempotency_key=idempotency_key,
        exit_reason=reason,
        market_observation_id=current_observation.observation_id,
        created_at_utc=as_of_utc,
        event_id=f"evt-prototype-close-reserve-{digest}",
    )
    if str(reserve.get("state") or "") == "FLAT":
        return PrototypeExitAdvanceResult(
            trade_id, "FLAT", "already_flat", reason.value, order_intent_id
        )
    if not bool(reserve.get("ok")):
        return PrototypeExitAdvanceResult(
            trade_id,
            "OPEN",
            str(reserve.get("error") or "close_reserve_rejected"),
            reason.value,
            order_intent_id,
        )

    persisted_id = str(reserve.get("order_intent_id") or order_intent_id)
    pending = conn.execute(
        sa.select(store.tables["order_intents"]).where(
            store.tables["order_intents"].c.order_intent_id == persisted_id
        )
    ).mappings().one()
    return _advance_pending_close(
        conn,
        store,
        trade_id=trade_id,
        pending=pending,
        current_observation=current_observation,
        as_of_utc=as_of_utc,
    )
