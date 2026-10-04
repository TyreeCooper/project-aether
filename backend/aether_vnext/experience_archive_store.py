"""Durable storage/query adapter for Phase-14 crisis/regime experience."""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.experience_archive import (
    CrisisRegimeArchiveEntry,
    CrisisRegimeArchiveQuery,
    retrieve_crisis_regime_archive,
)
from aether_vnext.store import VNextStore


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def load_crisis_regime_archive_entry(
    conn: Connection,
    *,
    store: VNextStore,
    archive_id: str,
) -> CrisisRegimeArchiveEntry | None:
    table = store.tables["crisis_regime_archive_entries"]
    row = conn.execute(
        sa.select(table).where(table.c.archive_id == str(archive_id))
    ).mappings().first()
    if row is None:
        return None
    return CrisisRegimeArchiveEntry(
        archive_id=str(row["archive_id"]),
        category=str(row["category"]),
        episode_ref=str(row["episode_ref"]),
        asset_ids=tuple(str(value) for value in (row["asset_ids"] or [])),
        regime_ids=tuple(str(value) for value in (row["regime_ids"] or [])),
        started_at_utc=_stored_utc(row["started_at_utc"]),
        ended_at_utc=_stored_utc(row["ended_at_utc"]),
        recorded_at_utc=_stored_utc(row["recorded_at_utc"]),
        source_record_ids=tuple(
            str(value) for value in (row["source_record_ids"] or [])
        ),
        synthetic=bool(row["synthetic"]),
        research_only=bool(row["research_only"]),
    )


def record_crisis_regime_archive_entry(
    conn: Connection,
    *,
    store: VNextStore,
    entry: CrisisRegimeArchiveEntry,
) -> None:
    existing = load_crisis_regime_archive_entry(
        conn,
        store=store,
        archive_id=entry.archive_id,
    )
    if existing is not None:
        if existing != entry:
            raise ValueError("conflicting immutable crisis/regime archive entry")
        return

    conn.execute(
        store.tables["crisis_regime_archive_entries"].insert().values(
            archive_id=entry.archive_id,
            category=entry.category,
            episode_ref=entry.episode_ref,
            asset_ids=list(entry.asset_ids),
            regime_ids=list(entry.regime_ids),
            started_at_utc=entry.started_at_utc,
            ended_at_utc=entry.ended_at_utc,
            recorded_at_utc=entry.recorded_at_utc,
            source_record_ids=list(entry.source_record_ids),
            synthetic=entry.synthetic,
            research_only=True,
        )
    )


def query_crisis_regime_archive(
    conn: Connection,
    *,
    store: VNextStore,
    query: CrisisRegimeArchiveQuery,
) -> tuple[CrisisRegimeArchiveEntry, ...]:
    """Query the durable archive without allowing future-record lookahead."""
    table = store.tables["crisis_regime_archive_entries"]
    stmt = sa.select(table.c.archive_id).where(
        table.c.recorded_at_utc <= query.as_of_utc
    )
    if query.categories:
        stmt = stmt.where(table.c.category.in_(query.categories))
    stmt = stmt.order_by(
        table.c.recorded_at_utc.desc(),
        table.c.ended_at_utc.desc(),
        table.c.archive_id.desc(),
    )

    entries: list[CrisisRegimeArchiveEntry] = []
    for archive_id in conn.execute(stmt).scalars():
        entry = load_crisis_regime_archive_entry(
            conn,
            store=store,
            archive_id=str(archive_id),
        )
        if entry is None:
            raise RuntimeError("crisis/regime archive entry disappeared during read")
        entries.append(entry)

    return retrieve_crisis_regime_archive(query=query, entries=tuple(entries))
