"""Runtime bridge for one FIRE Ticket through existing Firm Risk sizing.

No Risk formula is duplicated here. The bridge only validates the runtime market
snapshot shape and delegates the authoritative FIRE -> SIZE/REJECTED transition to
VNextStore.size_fire_ticket().
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

from sqlalchemy.engine import Connection

from aether_vnext.domain import MarketObservation
from aether_vnext.store import VNextStore


def size_runtime_fire_ticket(
    conn: Connection,
    store: VNextStore,
    *,
    ticket_id: str,
    current_observation: MarketObservation,
    current_observations: Mapping[str, MarketObservation],
    estimated_round_trip_cost_per_unit_usd: float,
    created_at_utc: datetime,
    event_id: str,
    broker_margin_cap_qty: float | None = None,
    firm_capital_cap_qty: float | None = None,
) -> dict[str, object]:
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    if not str(ticket_id).strip() or not str(event_id).strip():
        raise ValueError("ticket_id and event_id are required")

    asset_id = str(current_observation.asset_id).strip().lower()
    if not asset_id:
        raise ValueError("current observation asset_id is required")

    mapped = current_observations.get(asset_id)
    if mapped is None:
        raise ValueError(
            "current_observations must contain the ticket/current asset"
        )
    if mapped.observation_id != current_observation.observation_id:
        raise ValueError(
            "current_observations asset entry must match current observation"
        )

    return store.size_fire_ticket(
        conn,
        ticket_id=ticket_id,
        market_observation_id=current_observation.observation_id,
        current_observations=current_observations,
        estimated_round_trip_cost_per_unit_usd=(
            estimated_round_trip_cost_per_unit_usd
        ),
        created_at_utc=created_at_utc,
        event_id=event_id,
        broker_margin_cap_qty=broker_margin_cap_qty,
        firm_capital_cap_qty=firm_capital_cap_qty,
    )
