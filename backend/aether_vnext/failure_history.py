"""Point-in-time retrieval for AETHER vNext failure history."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.institutional_memory import FAILURE_CATEGORIES, FailureArchiveEntry
from aether_vnext.store import VNextStore


def _canonical_tuple(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an immutable tuple")
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{name} entries must be canonical text")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class FailureHistoryQuery:
    as_of_utc: datetime
    categories: tuple[str, ...] = ()
    memory_ids: tuple[str, ...] = ()
    trade_ids: tuple[str, ...] = ()
    limit: int = 50

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        _canonical_tuple("categories", self.categories)
        _canonical_tuple("memory_ids", self.memory_ids)
        _canonical_tuple("trade_ids", self.trade_ids)
        if any(category not in FAILURE_CATEGORIES for category in self.categories):
            raise ValueError("invalid failure-history category")
        if (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or self.limit <= 0
        ):
            raise ValueError("limit must be a positive integer")


@dataclass(frozen=True, slots=True)
class FailureHistory:
    as_of_utc: datetime
    entries: tuple[FailureArchiveEntry, ...]
    research_only: bool = True
    trade_influence_allowed: bool = False
    independent_evidence_credit: bool = False

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if self.research_only is not True:
            raise ValueError("failure history is research_only")
        if self.trade_influence_allowed is not False:
            raise ValueError("failure history cannot influence trades")
        if self.independent_evidence_credit is not False:
            raise ValueError(
                "failure history cannot receive independent evidence credit"
            )


def load_failure_history(
    conn: Connection,
    *,
    store: VNextStore,
    query: FailureHistoryQuery,
) -> FailureHistory:
    """Read only failures that were recorded by the point-in-time cutoff."""
    table = store.tables["failure_archive_entries"]
    stmt = sa.select(table.c.failure_id).where(
        table.c.recorded_at_utc <= query.as_of_utc
    )
    if query.categories:
        stmt = stmt.where(table.c.category.in_(query.categories))
    if query.memory_ids:
        stmt = stmt.where(table.c.memory_id.in_(query.memory_ids))
    if query.trade_ids:
        stmt = stmt.where(table.c.trade_id.in_(query.trade_ids))
    stmt = stmt.order_by(
        table.c.recorded_at_utc.desc(),
        table.c.failure_id.desc(),
    ).limit(query.limit)

    entries: list[FailureArchiveEntry] = []
    for failure_id in conn.execute(stmt).scalars():
        entry = store.load_failure_archive_entry(
            conn,
            failure_id=str(failure_id),
        )
        if entry is None:
            raise RuntimeError("failure archive entry disappeared during read")
        entries.append(entry)

    return FailureHistory(
        as_of_utc=query.as_of_utc,
        entries=tuple(entries),
    )
