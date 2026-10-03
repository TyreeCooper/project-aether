"""Runtime bridge for one Risk-sized Ticket through Clerk economics.

The bridge derives the same executable entry reference used by Risk from the current
market observation, then delegates cost/edge evaluation to Clerk and persistence to
the existing SIZE -> READY/REJECTED Store contract.

It does not alter Risk quantity, construct an ExitPlan, reserve capital, or execute.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.engine import Connection

from aether_vnext.clerk import ClerkDecision, evaluate_clerk_ready
from aether_vnext.domain import MarketObservation, TicketState
from aether_vnext.execution import entry_fill_price
from aether_vnext.exit_plan import ExitPlan
from aether_vnext.registry import registry_row
from aether_vnext.store import VNextStore


def evaluate_and_persist_clerk_ready(
    conn: Connection,
    store: VNextStore,
    *,
    ticket_id: str,
    current_observation: MarketObservation,
    first_target_price: float | None,
    atr: float | None,
    locate_ok: bool,
    exit_plan: ExitPlan | None,
    created_at_utc: datetime,
    event_id: str,
    cost_edge_multiple: float = 1.40,
    holding_days: float = 0.0,
    venue_borrow_rate_annual: float | None = None,
) -> tuple[ClerkDecision, dict[str, object]]:
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    if not str(ticket_id).strip() or not str(event_id).strip():
        raise ValueError("ticket_id and event_id are required")

    ticket = store.load_ticket(conn, ticket_id=ticket_id)
    if ticket is None:
        raise KeyError(f"unknown ticket: {ticket_id}")
    if ticket.state is not TicketState.SIZE:
        raise ValueError("Clerk runtime bridge requires SIZE ticket")
    if ticket.quantity is None or float(ticket.quantity) <= 0:
        raise RuntimeError("SIZE ticket missing Risk quantity")
    if current_observation.asset_id != ticket.lineage.asset_id:
        raise ValueError("current observation asset mismatch")
    if current_observation.spread_abs is None:
        raise ValueError("current observation spread_abs is required")

    entry_reference = entry_fill_price(
        current_observation,
        position_side=ticket.side,
    )
    decision = evaluate_clerk_ready(
        registry_row(ticket.lineage.asset_id),
        side=ticket.side,
        qty=float(ticket.quantity),
        entry_reference_price=entry_reference,
        spread_abs=float(current_observation.spread_abs),
        first_target_price=first_target_price,
        atr=atr,
        locate_ok=locate_ok,
        cost_edge_multiple=cost_edge_multiple,
        holding_days=holding_days,
        venue_borrow_rate_annual=venue_borrow_rate_annual,
    )
    quantity_before = float(ticket.quantity)
    result = store.apply_clerk_decision(
        conn,
        ticket_id=ticket_id,
        decision=decision,
        market_observation_id=current_observation.observation_id,
        exit_plan=exit_plan,
        created_at_utc=created_at_utc,
        event_id=event_id,
    )
    persisted = store.load_ticket(conn, ticket_id=ticket_id)
    quantity_after = float(persisted.quantity) if persisted is not None and persisted.quantity is not None else None
    if quantity_after != quantity_before:
        raise RuntimeError("Clerk cannot alter Risk-sized quantity")
    result = {
        **result,
        "predicate": "expected_edge >= 1.40x modeled_round_trip_cost",
        "cost_edge_multiple": cost_edge_multiple,
        "quantity_before_clerk": quantity_before,
        "quantity_after_clerk": quantity_after,
    }
    return decision, result
