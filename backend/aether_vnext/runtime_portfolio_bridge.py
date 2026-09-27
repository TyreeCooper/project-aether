"""Runtime bridge from a durable READY Ticket into Portfolio reservation.

This module is intentionally thin. It does not recalculate Risk quantity, Clerk
economics, reservation math, or broker ledger requirements. It resolves only
reviewed runtime routing facts and delegates the authoritative atomic READY ->
RESERVED transition to VNextStore.reserve_risk_checked_open_intent().
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

from sqlalchemy.engine import Connection

from aether_vnext.domain import MarketObservation, TicketState
from aether_vnext.playbooks import SEED_ASSET_CLUSTERS, cluster_for_asset
from aether_vnext.registry_runtime import materialize_bound_registry_row
from aether_vnext.seed_truth import ASSET_BROKER_ACCOUNT
from aether_vnext.store import VNextStore, open_intent_idempotency_key


def reserve_runtime_ready_ticket(
    conn: Connection,
    store: VNextStore,
    *,
    ticket_id: str,
    order_intent_id: str,
    current_observation: MarketObservation,
    current_observations: Mapping[str, MarketObservation],
    created_at_utc: datetime,
    event_id: str,
    desk_scope_id: str | None = None,
) -> dict[str, object]:
    """Reserve one READY ticket through the existing atomic Portfolio contract."""
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    if not str(ticket_id).strip():
        raise ValueError("ticket_id is required")
    if not str(order_intent_id).strip():
        raise ValueError("order_intent_id is required")
    if not str(event_id).strip():
        raise ValueError("event_id is required")

    ticket = store.load_ticket(conn, ticket_id=ticket_id)
    if ticket is None:
        raise KeyError(f"unknown ticket: {ticket_id}")
    if ticket.state is not TicketState.READY:
        raise ValueError("Portfolio runtime bridge requires READY ticket")
    if ticket.quantity is None or float(ticket.quantity) <= 0:
        raise RuntimeError("READY ticket missing Risk quantity")
    if ticket.stop_price is None or float(ticket.stop_price) <= 0:
        raise RuntimeError("READY ticket missing hard stop")
    if not str(ticket.exit_plan_id or "").strip():
        raise RuntimeError("READY ticket missing ExitPlan")

    asset_id = str(ticket.lineage.asset_id).strip().lower()
    if current_observation.asset_id != asset_id:
        raise ValueError("current observation asset mismatch")
    if current_observation.spread_bps is None:
        raise ValueError("current observation spread_bps is required")

    mapped = current_observations.get(asset_id)
    if mapped is None:
        raise ValueError(
            "current_observations must contain the READY ticket asset"
        )
    if mapped.observation_id != current_observation.observation_id:
        raise ValueError(
            "current_observations asset entry must match current observation"
        )

    runtime = store.load_runtime_registry_binding(conn, asset_id=asset_id)
    if runtime is None:
        raise RuntimeError("READY ticket runtime product binding missing")
    if runtime["configuration_hash"] != ticket.lineage.configuration_hash:
        raise RuntimeError(
            "READY ticket runtime product binding configuration mismatch"
        )

    bound_row = materialize_bound_registry_row(
        runtime["binding"],
        as_of_utc=created_at_utc,
    )
    if bound_row.asset_id != asset_id:
        raise RuntimeError("runtime product binding asset mismatch")
    symbol = str(bound_row.broker_symbol or "").strip()
    if not symbol:
        raise RuntimeError("runtime product binding missing broker symbol")

    broker_account_id = ASSET_BROKER_ACCOUNT.get(asset_id)
    if broker_account_id is None:
        raise RuntimeError("READY ticket has no canonical paper broker account")

    risk_cluster_id = str(ticket.lineage.risk_cluster_id or "").strip()
    canonical_cluster = cluster_for_asset(asset_id)
    if risk_cluster_id != canonical_cluster:
        raise RuntimeError("READY ticket canonical cluster drift")

    quantity = float(ticket.quantity)
    idempotency_key = open_intent_idempotency_key(
        ticket_id=ticket.ticket_id,
        side=ticket.side,
        quantity=quantity,
        asset_id=asset_id,
        horizon=ticket.horizon,
        signal_key=ticket.signal_key,
    )
    position_key = f"{asset_id}:{ticket.horizon}"

    return store.reserve_risk_checked_open_intent(
        conn,
        order_intent_id=order_intent_id,
        ticket_id=ticket.ticket_id,
        firm_event_id=ticket.lineage.firm_event_id,
        asset_id=asset_id,
        route_id=ticket.lineage.route_id,
        broker_account_id=broker_account_id,
        broker=bound_row.broker,
        venue=bound_row.venue,
        symbol=symbol,
        side=ticket.side,
        qty=quantity,
        order_type="MARKET_PAPER",
        reference_price=None,
        expected_fill=None,
        idempotency_key=idempotency_key,
        signal_key=ticket.signal_key,
        position_key=position_key,
        reserve_cash_usd=None,
        reserve_margin_usd=None,
        ready_spread_bps=float(current_observation.spread_bps),
        hard_stop_price=float(ticket.stop_price),
        exit_plan_id=ticket.exit_plan_id,
        submit_timeout_at=None,
        policy_version=ticket.lineage.policy_version,
        configuration_hash=ticket.lineage.configuration_hash,
        market_observation_id=current_observation.observation_id,
        created_at_utc=created_at_utc,
        event_id=event_id,
        actor="Portfolio",
        risk_cluster_id=risk_cluster_id,
        cluster_by_asset=SEED_ASSET_CLUSTERS,
        current_observations=current_observations,
        desk_scope_id=desk_scope_id,
    )
