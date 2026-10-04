"""Durable point-in-time query bridge for AETHER vNext institutional memory."""
from __future__ import annotations

from sqlalchemy.engine import Connection
import sqlalchemy as sa

from aether_vnext.institutional_analogs import (
    HistoricalDecisionContext,
    HistoricalDecisionContextQuery,
    retrieve_historical_decision_context,
)
from aether_vnext.store import VNextStore


def load_historical_decision_context(
    conn: Connection,
    *,
    store: VNextStore,
    query: HistoricalDecisionContextQuery,
) -> HistoricalDecisionContext:
    """Load only point-in-time eligible memories, then apply research filters.

    The SQL predicate enforces the availability cutoff before records leave the
    durable book. Relevance-tag matching remains in the pure retrieval layer so
    behavior is identical across PostgreSQL and SQLite test books.
    """
    table = store.tables["institutional_memories"]
    stmt = sa.select(table.c.memory_id).where(
        table.c.recorded_at_utc <= query.as_of_utc
    )

    for column_name, value in (
        ("route_id", query.route_id),
        ("playbook_id", query.playbook_id),
        ("playbook_version", query.playbook_version),
        ("configuration_hash", query.configuration_hash),
    ):
        if value is not None:
            stmt = stmt.where(getattr(table.c, column_name) == value)

    stmt = stmt.order_by(
        table.c.recorded_at_utc.desc(),
        table.c.occurred_at_utc.desc(),
        table.c.memory_id.desc(),
    )
    memory_ids = tuple(conn.execute(stmt).scalars())

    memories = []
    for memory_id in memory_ids:
        memory = store.load_institutional_memory(
            conn,
            memory_id=str(memory_id),
        )
        if memory is None:
            raise RuntimeError("institutional memory disappeared during read")
        memories.append(memory)

    return retrieve_historical_decision_context(
        query=query,
        memories=tuple(memories),
    )
