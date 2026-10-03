from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.failure_history import FailureHistoryQuery, load_failure_history
from aether_vnext.institutional_memory import FailureArchiveEntry
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 16, 0, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _failure(
    failure_id: str,
    *,
    memory_id: str = "memory-1",
    trade_id: str = "trade-1",
    category: str = "abnormal_slippage_spread_widening",
    recorded_offset: int = -1,
) -> FailureArchiveEntry:
    return FailureArchiveEntry(
        failure_id=failure_id,
        memory_id=memory_id,
        trade_id=trade_id,
        category=category,
        reason="observed failure",
        recovery_lesson="retain as scar tissue",
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(memory_id,),
    )


def test_failure_history_blocks_future_recorded_entries() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_failure_archive_entry(conn, _failure("visible", recorded_offset=-2))
        store.record_failure_archive_entry(conn, _failure("future", recorded_offset=1))

    with engine.begin() as conn:
        history = load_failure_history(
            conn,
            store=store,
            query=FailureHistoryQuery(as_of_utc=T0),
        )

    assert tuple(row.failure_id for row in history.entries) == ("visible",)
    assert history.research_only is True
    assert history.trade_influence_allowed is False
    assert history.independent_evidence_credit is False


def test_failure_history_filters_by_memory_trade_and_category() -> None:
    engine, store = _store()
    wanted = _failure(
        "wanted",
        memory_id="memory-a",
        trade_id="trade-a",
        category="model_assumption_failure",
        recorded_offset=-3,
    )
    wrong_memory = _failure(
        "wrong-memory",
        memory_id="memory-b",
        trade_id="trade-a",
        category="model_assumption_failure",
        recorded_offset=-2,
    )
    wrong_category = _failure(
        "wrong-category",
        memory_id="memory-a",
        trade_id="trade-a",
        category="stale_malformed_data",
        recorded_offset=-1,
    )

    with engine.begin() as conn:
        for entry in (wanted, wrong_memory, wrong_category):
            store.record_failure_archive_entry(conn, entry)

    with engine.begin() as conn:
        history = load_failure_history(
            conn,
            store=store,
            query=FailureHistoryQuery(
                as_of_utc=T0,
                categories=("model_assumption_failure",),
                memory_ids=("memory-a",),
                trade_ids=("trade-a",),
            ),
        )

    assert tuple(row.failure_id for row in history.entries) == ("wanted",)


def test_failure_history_limit_is_deterministic_newest_first() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_failure_archive_entry(conn, _failure("old", recorded_offset=-4))
        store.record_failure_archive_entry(conn, _failure("new", recorded_offset=-1))
        store.record_failure_archive_entry(conn, _failure("middle", recorded_offset=-2))

    with engine.begin() as conn:
        history = load_failure_history(
            conn,
            store=store,
            query=FailureHistoryQuery(as_of_utc=T0, limit=2),
        )

    assert tuple(row.failure_id for row in history.entries) == ("new", "middle")
