"""Canonical read-only vNext book projection for the Phase-16 shadow Floor."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.operator_floor import (
    FloorUniverseStation,
    OpenPositionCockpit,
    SeatQueueSnapshot,
    UnifiedFirmFloorSnapshot,
)
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.store import VNextStore


_DISPLAY_PRIORITY = {
    "NO": 0,
    "WATCH": 10,
    "FIRE": 20,
    "SIZE": 30,
    "READY": 40,
    "ORDER": 50,
    "OPEN": 60,
    "HALT": 70,
}

_SEAT_BY_STATE = {
    "NO": "Universe",
    "WATCH": "Scout",
    "FIRE": "Sniper",
    "SIZE": "Risk",
    "READY": "Clerk",
    "ORDER": "Portfolio",
    "OPEN": "Floor",
    "HALT": "Governor",
}


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _candidate(
    state: str,
    *,
    blocker: str | None = None,
    blocker_reason: str | None = None,
) -> tuple[int, str, str | None, str | None]:
    if state not in _DISPLAY_PRIORITY:
        raise ValueError(f"unsupported Floor display state: {state}")
    return (
        _DISPLAY_PRIORITY[state],
        state,
        blocker,
        blocker_reason,
    )


def _select_dominant(
    candidates: list[tuple[int, str, str | None, str | None]],
) -> tuple[str, str, str | None, str | None]:
    if not candidates:
        return ("NO", "Universe", None, None)
    _, state, blocker, blocker_reason = max(candidates, key=lambda row: row[0])
    return (state, _SEAT_BY_STATE[state], blocker, blocker_reason)


def _build_open_cockpit(
    *,
    active: Mapping[str, Any],
    trade: Mapping[str, Any],
    exit_plan: Mapping[str, Any],
    mark: float | None,
) -> OpenPositionCockpit:
    if str(active["trade_id"]) != str(trade["trade_id"]):
        raise RuntimeError("active position/open trade identity mismatch")
    if str(active["asset_id"]) != str(trade["asset_id"]):
        raise RuntimeError("active position/open trade asset mismatch")
    hard_stop = exit_plan.get("hard_stop_price")
    if hard_stop is None:
        raise RuntimeError("open trade exit plan is missing hard_stop_price")
    opened = trade["opened_at_utc"]
    if not isinstance(opened, datetime):
        raise RuntimeError("open trade opened_at_utc is invalid")
    return OpenPositionCockpit(
        position_key=str(active["position_key"]),
        trade_id=str(active["trade_id"]),
        asset_id=str(active["asset_id"]),
        horizon=str(active["horizon"]),
        side=str(active["side"]),
        quantity=float(active["quantity"]),
        average_entry_price=float(trade["avg_entry_price"]),
        mark_price=(None if mark is None else float(mark)),
        hard_stop_price=float(hard_stop),
        opened_at_utc=_stored_utc(opened),
    )


def build_shadow_floor_snapshot(
    conn: Connection,
    *,
    store: VNextStore,
    as_of_utc: datetime,
) -> UnifiedFirmFloorSnapshot:
    """Project canonical vNext state without writing or inventing attention rank."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    t = store.tables

    latest_mark: dict[str, float | None] = {}
    observations = conn.execute(
        sa.select(t["market_observations"])
        .where(t["market_observations"].c.received_ts <= as_of_utc)
        .order_by(t["market_observations"].c.received_ts.desc())
    ).mappings()
    for row in observations:
        asset_id = str(row["asset_id"])
        if asset_id not in latest_mark:
            latest_mark[asset_id] = (
                None if row["mark"] is None else float(row["mark"])
            )

    candidates: dict[
        str,
        list[tuple[int, str, str | None, str | None]],
    ] = {asset_id: [] for asset_id in SEED_REGISTRY}
    routes: dict[str, set[str]] = {asset_id: set() for asset_id in SEED_REGISTRY}

    lineages = conn.execute(
        sa.select(t["decision_lineage"]).where(
            t["decision_lineage"].c.created_at_utc <= as_of_utc
        )
    ).mappings()
    for row in lineages:
        asset_id = str(row["asset_id"])
        if asset_id in routes:
            routes[asset_id].add(str(row["route_id"]))

    setups = tuple(
        conn.execute(
            sa.select(t["setups"]).where(
                t["setups"].c.created_at_utc <= as_of_utc,
                t["setups"].c.state.in_(("WATCH", "FIRE")),
            )
        ).mappings()
    )
    for row in setups:
        asset_id = str(row["asset_id"])
        if asset_id not in candidates:
            raise RuntimeError(f"setup references unsupported asset: {asset_id}")
        state = str(row["state"])
        candidates[asset_id].append(
            _candidate(
                state,
                blocker=(
                    None
                    if row["first_killed_by"] is None
                    else str(row["first_killed_by"])
                ),
                blocker_reason=(
                    None
                    if row["first_kill_reason"] is None
                    else str(row["first_kill_reason"])
                ),
            )
        )
        routes[asset_id].add(str(row["route_id"]))

    tickets = tuple(
        conn.execute(
            sa.select(t["tickets"]).where(
                t["tickets"].c.created_at_utc <= as_of_utc,
                t["tickets"].c.state.in_(("FIRE", "SIZE", "READY")),
            )
        ).mappings()
    )
    for row in tickets:
        asset_id = str(row["asset_id"])
        if asset_id not in candidates:
            raise RuntimeError(f"ticket references unsupported asset: {asset_id}")
        candidates[asset_id].append(
            _candidate(
                str(row["state"]),
                blocker=(
                    None
                    if row["first_killed_by"] is None
                    else str(row["first_killed_by"])
                ),
                blocker_reason=(
                    None
                    if row["first_kill_reason"] is None
                    else str(row["first_kill_reason"])
                ),
            )
        )
        routes[asset_id].add(str(row["route_id"]))

    order_intents = tuple(
        conn.execute(
            sa.select(t["order_intents"]).where(
                t["order_intents"].c.created_at_utc <= as_of_utc,
                t["order_intents"].c.state.in_(
                    ("RESERVED", "SUBMITTED", "ACCEPTED", "PARTIAL")
                ),
            )
        ).mappings()
    )
    for row in order_intents:
        asset_id = str(row["asset_id"])
        if asset_id not in candidates:
            raise RuntimeError(
                f"order intent references unsupported asset: {asset_id}"
            )
        candidates[asset_id].append(
            _candidate(
                "ORDER",
                blocker=(
                    None
                    if row["first_killed_by"] is None
                    else str(row["first_killed_by"])
                ),
                blocker_reason=(
                    None
                    if row["first_kill_reason"] is None
                    else str(row["first_kill_reason"])
                ),
            )
        )
        routes[asset_id].add(str(row["route_id"]))

    active_positions = tuple(
        conn.execute(sa.select(t["active_positions"])).mappings()
    )
    open_count = {asset_id: 0 for asset_id in SEED_REGISTRY}
    open_cockpits: list[OpenPositionCockpit] = []
    for active in active_positions:
        asset_id = str(active["asset_id"])
        if asset_id not in candidates:
            raise RuntimeError(
                f"active position references unsupported asset: {asset_id}"
            )
        trade = conn.execute(
            sa.select(t["open_trades"]).where(
                t["open_trades"].c.trade_id == str(active["trade_id"])
            )
        ).mappings().first()
        if trade is None:
            raise RuntimeError("active position missing canonical open trade")
        exit_plan = conn.execute(
            sa.select(t["exit_plans"]).where(
                t["exit_plans"].c.exit_plan_id == str(trade["exit_plan_id"])
            )
        ).mappings().first()
        if exit_plan is None:
            raise RuntimeError("open trade missing canonical exit plan")
        candidates[asset_id].append(_candidate("OPEN"))
        open_count[asset_id] += 1
        routes[asset_id].add(str(trade["route_id"]))
        open_cockpits.append(
            _build_open_cockpit(
                active=active,
                trade=trade,
                exit_plan=exit_plan,
                mark=latest_mark.get(asset_id),
            )
        )

    halts = tuple(
        conn.execute(
            sa.select(t["governor_state"]).where(
                t["governor_state"].c.state == "HALT",
                t["governor_state"].c.effective_at_utc <= as_of_utc,
            )
        ).mappings()
    )
    for row in halts:
        scope_type = str(row["scope_type"])
        scope_id = row["scope_id"]
        reason = None if row["reason"] is None else str(row["reason"])
        if scope_type == "desk":
            affected = tuple(SEED_REGISTRY)
        elif scope_type == "product" and scope_id is not None:
            affected = (str(scope_id).lower(),)
        elif scope_type == "route" and scope_id is not None:
            route_id = str(scope_id)
            affected = tuple(
                asset_id
                for asset_id, route_ids in routes.items()
                if route_id in route_ids
            )
        else:
            affected = ()
        for asset_id in affected:
            if asset_id in candidates:
                candidates[asset_id].append(
                    _candidate(
                        "HALT",
                        blocker="Governor",
                        blocker_reason=reason,
                    )
                )

    full_universe: list[FloorUniverseStation] = []
    for asset_id in sorted(SEED_REGISTRY):
        registry = SEED_REGISTRY[asset_id]
        state, seat, blocker, blocker_reason = _select_dominant(
            candidates[asset_id]
        )
        full_universe.append(
            FloorUniverseStation(
                asset_id=asset_id,
                symbol=registry.canonical_symbol,
                product_type=registry.product_type.value,
                dominant_state=state,
                seat_owner=seat,
                first_blocker=blocker,
                first_blocker_reason=blocker_reason,
                mark=latest_mark.get(asset_id),
                open_position_count=open_count[asset_id],
                route_ids=tuple(sorted(routes[asset_id])),
            )
        )

    queue_items: dict[tuple[str, str], set[str]] = {}
    for row in setups:
        key = (
            "Scout" if str(row["state"]) == "WATCH" else "Sniper",
            str(row["state"]),
        )
        queue_items.setdefault(key, set()).add(str(row["setup_id"]))
    for row in tickets:
        state = str(row["state"])
        seat = {
            "FIRE": "Sniper",
            "SIZE": "Risk",
            "READY": "Clerk",
        }[state]
        queue_items.setdefault((seat, state), set()).add(str(row["ticket_id"]))
    if order_intents:
        queue_items[("Portfolio", "ORDER")] = {
            str(row["order_intent_id"]) for row in order_intents
        }
    if halts:
        queue_items[("Governor", "HALT")] = {
            str(row["scope_key"]) for row in halts
        }

    seat_queues = tuple(
        SeatQueueSnapshot(
            seat=seat,
            state=state,
            item_ids=tuple(sorted(item_ids)),
        )
        for (seat, state), item_ids in sorted(queue_items.items())
    )

    return UnifiedFirmFloorSnapshot(
        as_of_utc=as_of_utc,
        full_universe=tuple(full_universe),
        top12_attention=(),
        seat_queues=seat_queues,
        open_cockpits=tuple(
            sorted(open_cockpits, key=lambda row: row.position_key)
        ),
        inspection_drawer=None,
    )
