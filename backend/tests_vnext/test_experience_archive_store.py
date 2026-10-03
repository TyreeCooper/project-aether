from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.experience_archive import (
    CrisisRegimeArchiveEntry,
    CrisisRegimeArchiveQuery,
)
from aether_vnext.experience_archive_store import (
    load_crisis_regime_archive_entry,
    query_crisis_regime_archive,
    record_crisis_regime_archive_entry,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 15, 30, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _entry(
    archive_id: str = "archive-1",
    *,
    category: str = "liquidity_crisis",
    assets: tuple[str, ...] = ("btc",),
    regimes: tuple[str, ...] = ("risk_off",),
    recorded_offset: int = -1,
    episode_ref: str = "episode-1",
) -> CrisisRegimeArchiveEntry:
    return CrisisRegimeArchiveEntry(
        archive_id=archive_id,
        category=category,
        episode_ref=episode_ref,
        asset_ids=assets,
        regime_ids=regimes,
        started_at_utc=T0 - timedelta(hours=2),
        ended_at_utc=T0 - timedelta(hours=1),
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(f"source-{archive_id}",),
    )


def test_archive_round_trip_is_idempotent_and_conflict_safe() -> None:
    engine, store = _store()
    entry = _entry()

    with engine.begin() as conn:
        record_crisis_regime_archive_entry(conn, store=store, entry=entry)
        record_crisis_regime_archive_entry(conn, store=store, entry=entry)

    with engine.begin() as conn:
        loaded = load_crisis_regime_archive_entry(
            conn,
            store=store,
            archive_id=entry.archive_id,
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["crisis_regime_archive_entries"]
            )
        ).scalar_one()

    assert loaded == entry
    assert count == 1

    with pytest.raises(
        ValueError,
        match="conflicting immutable crisis/regime archive entry",
    ):
        with engine.begin() as conn:
            record_crisis_regime_archive_entry(
                conn,
                store=store,
                entry=_entry(episode_ref="changed"),
            )


def test_point_in_time_query_excludes_future_recorded_episode() -> None:
    engine, store = _store()
    visible = _entry("visible", recorded_offset=-2)
    future = _entry("future", recorded_offset=1)

    with engine.begin() as conn:
        record_crisis_regime_archive_entry(conn, store=store, entry=visible)
        record_crisis_regime_archive_entry(conn, store=store, entry=future)

    with engine.begin() as conn:
        result = query_crisis_regime_archive(
            conn,
            store=store,
            query=CrisisRegimeArchiveQuery(as_of_utc=T0),
        )

    assert tuple(row.archive_id for row in result) == ("visible",)


def test_durable_query_preserves_explicit_asset_regime_filters() -> None:
    engine, store = _store()
    wanted = _entry(
        "wanted",
        category="scheduled_macro_surprise",
        assets=("btc", "eth"),
        regimes=("risk_off",),
        recorded_offset=-3,
    )
    wrong_asset = _entry(
        "wrong-asset",
        category="scheduled_macro_surprise",
        assets=("mes",),
        regimes=("risk_off",),
        recorded_offset=-2,
    )
    wrong_category = _entry(
        "wrong-category",
        category="regulatory_shock",
        assets=("btc",),
        regimes=("risk_off",),
        recorded_offset=-1,
    )

    with engine.begin() as conn:
        for entry in (wanted, wrong_asset, wrong_category):
            record_crisis_regime_archive_entry(conn, store=store, entry=entry)

    with engine.begin() as conn:
        result = query_crisis_regime_archive(
            conn,
            store=store,
            query=CrisisRegimeArchiveQuery(
                as_of_utc=T0,
                categories=("scheduled_macro_surprise",),
                asset_ids=("btc",),
                regime_ids=("risk_off",),
            ),
        )

    assert tuple(row.archive_id for row in result) == ("wanted",)
