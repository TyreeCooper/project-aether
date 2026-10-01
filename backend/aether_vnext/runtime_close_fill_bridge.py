"""Runtime bridge from SUBMITTED paper CLOSE intents to durable FLAT trades.

Execution math stays in execution.py; accounting/book mutation stays in VNextStore.
This bridge validates runtime routing, applies the paper close-fill decision, derives
product-correct realized economics, and delegates either zero-fill rejection or
atomic CLOSE FILLED -> FLAT persistence.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.costs import default_short_borrow_usd, leg_fee_usd
from aether_vnext.domain import OrderIntentState
from aether_vnext.execution import (
    fill_submitted_paper_flatten_intent,
    gross_pnl_usd,
)
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.runtime_product_policy import resolve_runtime_product
from aether_vnext.store import VNextStore


_TERMINAL = frozenset(
    {
        OrderIntentState.FILLED,
        OrderIntentState.REJECTED,
        OrderIntentState.CANCELLED,
        OrderIntentState.CANCELLED_STALE,
    }
)


def _stored_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def fill_runtime_submitted_close(
    conn: Connection,
    store: VNextStore,
    *,
    order_intent_id: str,
    fill_market_observation_id: str,
    filled_at_utc: datetime,
    event_id: str,
) -> dict[str, object]:
    """Apply one paper CLOSE fill-time decision and persist FLAT or rejection."""
    if filled_at_utc.tzinfo is None:
        raise ValueError("filled_at_utc must be timezone-aware")
    for name, value in (
        ("order_intent_id", order_intent_id),
        ("fill_market_observation_id", fill_market_observation_id),
        ("event_id", event_id),
    ):
        if not str(value).strip():
            raise ValueError(f"{name} is required")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("runtime close-fill safety invariant is not paper-only")

    intent = store.load_order_intent(
        conn,
        order_intent_id=order_intent_id,
    )
    if intent is None:
        raise KeyError(f"unknown order intent: {order_intent_id}")
    if intent.intent_kind != "CLOSE":
        raise ValueError("runtime CLOSE fill bridge requires CLOSE intent")
    if intent.order_type != "MARKET_PAPER":
        raise RuntimeError("runtime CLOSE fill bridge requires MARKET_PAPER")

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

    trade_id = str(intent.trade_id or "").strip()
    if not trade_id:
        raise RuntimeError("SUBMITTED CLOSE intent missing trade identity")

    trades = store.tables["open_trades"]
    trade = conn.execute(
        sa.select(trades).where(trades.c.trade_id == trade_id)
    ).mappings().first()
    if trade is None:
        raise RuntimeError("SUBMITTED CLOSE intent no longer maps to open trade")

    observation = store.load_market_observation(
        conn,
        observation_id=fill_market_observation_id,
    )
    if observation is None:
        raise KeyError(
            f"unknown close fill market observation: {fill_market_observation_id}"
        )
    asset_id = str(trade["asset_id"]).strip().lower()
    if observation.asset_id != asset_id:
        raise ValueError("close fill market observation asset mismatch")

    resolved = resolve_runtime_product(
        conn,
        store,
        asset_id=asset_id,
        as_of_utc=filled_at_utc,
    )
    if resolved.configuration_hash != str(trade["configuration_hash"]):
        raise RuntimeError(
            "SUBMITTED CLOSE runtime product binding configuration mismatch"
        )
    bound_row = resolved.product
    if (
        intent.broker != bound_row.broker
        or intent.venue != bound_row.venue
        or intent.symbol_executed != bound_row.broker_symbol
    ):
        raise RuntimeError("SUBMITTED CLOSE runtime routing drift")
    if bound_row.stale_threshold_ms is None:
        raise RuntimeError("runtime product binding stale threshold missing")

    transition = fill_submitted_paper_flatten_intent(
        intent,
        observation=observation,
        registry_row=bound_row,
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
            first_killed_by=None,
            fill_market_observation_id=fill_market_observation_id,
        )
    if decided.state is not OrderIntentState.FILLED:
        raise RuntimeError(
            f"unexpected paper close transition state: {decided.state.value}"
        )
    if (
        decided.filled_at is None
        or decided.avg_fill_price is None
        or decided.slip_usd is None
        or decided.slip_bps is None
    ):
        raise RuntimeError("paper close transition missing fill economics")

    opening_intent = store.load_order_intent(
        conn,
        order_intent_id=str(trade["order_intent_id"]),
    )
    if opening_intent is None:
        raise RuntimeError("open trade missing opening intent")

    qty = float(trade["quantity"])
    entry_price = float(trade["avg_entry_price"])
    exit_price = float(decided.avg_fill_price)
    side = str(trade["side"]).strip().lower()
    if side not in {"long", "short"}:
        raise RuntimeError("open trade has invalid side")

    gross = gross_pnl_usd(
        bound_row,
        position_side=side,
        qty=qty,
        entry_price=entry_price,
        exit_price=exit_price,
    )
    entry_fee = leg_fee_usd(
        bound_row,
        qty=qty,
        price=entry_price,
        side="buy" if side == "long" else "sell",
    )
    exit_fee = leg_fee_usd(
        bound_row,
        qty=qty,
        price=exit_price,
        side="sell" if side == "long" else "buy",
    )
    fees = entry_fee + exit_fee

    opened_at = _stored_utc(trade["opened_at_utc"])
    holding_days = max(
        0.0,
        (filled_at_utc - opened_at).total_seconds() / 86_400.0,
    )
    carry = (
        default_short_borrow_usd(
            bound_row,
            qty=qty,
            price=entry_price,
            holding_days=holding_days,
        )
        if side == "short" and bound_row.borrow_required
        else 0.0
    )

    entry_slip = float(opening_intent.slip_usd or 0.0)
    exit_slip = float(decided.slip_usd)
    total_cost = fees + carry + entry_slip + exit_slip
    net = gross - fees - carry

    return store.finalize_filled_flat(
        conn,
        close_order_intent_id=order_intent_id,
        fill_market_observation_id=fill_market_observation_id,
        filled_at_utc=decided.filled_at,
        filled_qty=float(decided.filled_qty),
        exit_price=exit_price,
        gross_pnl_usd=gross,
        net_pnl_usd=net,
        total_cost_usd=total_cost,
        fees_usd=fees,
        slippage_usd=exit_slip,
        slippage_bps=float(decided.slip_bps),
        mfe_usd=None,
        mae_usd=None,
        capture_efficiency=None,
        event_id=event_id,
        actor="paper-adapter",
        carry_usd=carry,
    )
