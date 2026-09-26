"""Restart/recovery view for AETHER vNext.

Loading state is read-only. It must never seed cash, create trades, consume signals,
or mutate policy. Reconciliation may later compare this snapshot with broker truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class RestartSnapshot:
    product_registry: tuple[dict[str, Any], ...]
    decision_lineage: tuple[dict[str, Any], ...]
    policy_snapshots: tuple[dict[str, Any], ...]
    governor_state: tuple[dict[str, Any], ...]
    broker_ledgers: tuple[dict[str, Any], ...]
    in_flight_setups: tuple[dict[str, Any], ...]
    in_flight_tickets: tuple[dict[str, Any], ...]
    in_flight_order_intents: tuple[dict[str, Any], ...]
    active_positions: tuple[dict[str, Any], ...]
    open_trade_records: tuple[dict[str, Any], ...]
    exit_plans: tuple[dict[str, Any], ...]
    review_cards: tuple[dict[str, Any], ...]
    route_review_state: tuple[dict[str, Any], ...]
    consumed_signals: tuple[dict[str, Any], ...]
    mutation_idempotency: tuple[dict[str, Any], ...]
    reconciliation_runs: tuple[dict[str, Any], ...]
    event_count: int


def _rows(conn: Connection, table: sa.Table, *where) -> tuple[dict[str, Any], ...]:
    stmt = sa.select(table)
    if where:
        stmt = stmt.where(*where)
    return tuple(dict(row) for row in conn.execute(stmt).mappings())


def load_restart_snapshot(
    conn: Connection,
    *,
    store: VNextStore,
) -> RestartSnapshot:
    t = store.tables

    # No writes are allowed in this function. In-flight is intentionally narrow:
    # completed/rejected terminal records remain durable but are not resumed.
    setups = _rows(
        conn,
        t["setups"],
        t["setups"].c.state.in_(("WATCH", "FIRE")),
    )
    tickets = _rows(
        conn,
        t["tickets"],
        t["tickets"].c.state.in_(("FIRE", "SIZE", "READY")),
    )
    intents = _rows(
        conn,
        t["order_intents"],
        t["order_intents"].c.state.in_(
            ("RESERVED", "SUBMITTED", "ACCEPTED", "PARTIAL")
        ),
    )

    event_count = int(
        conn.execute(
            sa.select(sa.func.count()).select_from(t["event_ledger"])
        ).scalar_one()
    )

    return RestartSnapshot(
        product_registry=_rows(conn, t["product_registry_state"]),
        decision_lineage=_rows(conn, t["decision_lineage"]),
        policy_snapshots=_rows(conn, t["policy_snapshots"]),
        governor_state=_rows(conn, t["governor_state"]),
        broker_ledgers=_rows(conn, t["broker_account_ledgers"]),
        in_flight_setups=setups,
        in_flight_tickets=tickets,
        in_flight_order_intents=intents,
        active_positions=_rows(conn, t["active_positions"]),
        open_trade_records=_rows(conn, t["open_trades"]),
        exit_plans=_rows(conn, t["exit_plans"]),
        review_cards=_rows(conn, t["review_cards"]),
        route_review_state=_rows(conn, t["route_review_state"]),
        consumed_signals=_rows(conn, t["signal_consumptions"]),
        mutation_idempotency=_rows(conn, t["mutation_idempotency"]),
        reconciliation_runs=_rows(conn, t["reconciliation_runs"]),
        event_count=event_count,
    )
