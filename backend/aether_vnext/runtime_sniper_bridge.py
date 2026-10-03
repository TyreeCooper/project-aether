"""Runtime bridge for one durable WATCH Setup through Sniper FIRE evaluation.

The bridge composes existing Sniper and Store contracts only. It does not calculate
the hard stop, size Risk, evaluate Clerk economics, or execute an order.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.engine import Connection

from aether_vnext.bars import Bar
from aether_vnext.domain import MarketObservation
from aether_vnext.sniper import SniperDecision, evaluate_sniper_fire
from aether_vnext.store import VNextStore


def evaluate_and_persist_sniper_ticket(
    conn: Connection,
    store: VNextStore,
    *,
    setup_id: str,
    ticket_id: str,
    completed_bar: Bar | None,
    current_observation: MarketObservation,
    hard_stop_price: float | None,
    as_of_utc: datetime,
    grain_valid: bool,
    invalidation_hit: bool,
    created_at_utc: datetime,
    desk_scope_id: str | None = None,
) -> tuple[SniperDecision, dict[str, object]]:
    if as_of_utc.tzinfo is None or created_at_utc.tzinfo is None:
        raise ValueError("runtime timestamps must be timezone-aware")
    if not str(setup_id).strip() or not str(ticket_id).strip():
        raise ValueError("setup_id and ticket_id are required")

    setup = store.load_setup(conn, setup_id=setup_id)
    if setup is None:
        raise KeyError(f"unknown setup: {setup_id}")
    if current_observation.asset_id != setup.lineage.asset_id:
        raise ValueError("current observation asset mismatch")

    decision = evaluate_sniper_fire(
        setup,
        completed_bar=completed_bar,
        current_observation=current_observation,
        hard_stop_price=hard_stop_price,
        as_of_utc=as_of_utc,
        grain_valid=grain_valid,
        invalidation_hit=invalidation_hit,
    )
    result = store.record_sniper_ticket(
        conn,
        setup_id=setup_id,
        ticket_id=ticket_id,
        decision=decision,
        market_observation_id=current_observation.observation_id,
        created_at_utc=created_at_utc,
        desk_scope_id=desk_scope_id,
    )
    return decision, result
