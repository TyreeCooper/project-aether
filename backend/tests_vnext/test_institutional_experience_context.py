from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.experience_archive import CrisisRegimeArchiveEntry
from aether_vnext.experience_archive_store import record_crisis_regime_archive_entry
from aether_vnext.institutional_experience_context import (
    InstitutionalExperienceQuery,
    load_institutional_experience_context,
)
from aether_vnext.institutional_memory import FailureArchiveEntry, InstitutionalMemoryRecord
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 16, 30, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _memory(
    memory_id: str,
    *,
    route_id: str = "btc:1h:trend",
    recorded_offset: int = -5,
) -> InstitutionalMemoryRecord:
    return InstitutionalMemoryRecord(
        memory_id=memory_id,
        trade_id=f"trade-{memory_id}",
        route_id=route_id,
        playbook_id="pb-trend",
        playbook_version="v1",
        configuration_hash="cfg-1",
        market_state_ref=f"market-{memory_id}",
        information_state_ref=f"info-{memory_id}",
        signal_ref=f"signal-{memory_id}",
        decision_ref=f"decision-{memory_id}",
        expected_outcome_ref=f"expected-{memory_id}",
        actual_outcome_ref=f"actual-{memory_id}",
        execution_quality_ref=f"execution-{memory_id}",
        risk_state_ref=f"risk-{memory_id}",
        success_failure_reason="observed outcome",
        lesson="retain verified lesson",
        future_relevance=("trend_up", "btc"),
        occurred_at_utc=T0 + timedelta(minutes=recorded_offset - 1),
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(f"source-{memory_id}",),
    )


def _failure(memory_id: str, *, recorded_offset: int = -4) -> FailureArchiveEntry:
    return FailureArchiveEntry(
        failure_id=f"failure-{memory_id}",
        memory_id=memory_id,
        trade_id=f"trade-{memory_id}",
        category="model_assumption_failure",
        reason="observed miss",
        recovery_lesson="retain miss as scar tissue",
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(memory_id,),
    )


def _crisis(
    archive_id: str,
    *,
    recorded_offset: int = -3,
) -> CrisisRegimeArchiveEntry:
    return CrisisRegimeArchiveEntry(
        archive_id=archive_id,
        category="liquidity_crisis",
        episode_ref=f"episode-{archive_id}",
        asset_ids=("btc",),
        regime_ids=("risk_off",),
        started_at_utc=T0 - timedelta(hours=2),
        ended_at_utc=T0 - timedelta(hours=1),
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(f"source-{archive_id}",),
    )


def test_context_links_only_failures_from_matched_decision_memories() -> None:
    engine, store = _store()
    matched = _memory("matched")
    other = _memory("other", route_id="eth:1h:trend")
    with engine.begin() as conn:
        store.record_institutional_memory(conn, matched)
        store.record_institutional_memory(conn, other)
        store.record_failure_archive_entry(conn, _failure("matched"))
        store.record_failure_archive_entry(conn, _failure("other"))
        record_crisis_regime_archive_entry(conn, store=store, entry=_crisis("crisis-1"))

    with engine.begin() as conn:
        context = load_institutional_experience_context(
            conn,
            store=store,
            query=InstitutionalExperienceQuery(
                as_of_utc=T0,
                route_id="btc:1h:trend",
                failure_categories=("model_assumption_failure",),
                crisis_categories=("liquidity_crisis",),
                crisis_asset_ids=("btc",),
            ),
        )

    assert context.decision_context.matched_memory_ids == ("matched",)
    assert tuple(row.failure_id for row in context.failure_history.entries) == (
        "failure-matched",
    )
    assert tuple(row.archive_id for row in context.crisis_regime_entries) == (
        "crisis-1",
    )
    assert context.research_only is True
    assert context.trade_influence_allowed is False
    assert context.independent_evidence_credit is False


def test_context_uses_one_as_of_cutoff_across_all_experience_channels() -> None:
    engine, store = _store()
    visible = _memory("visible", recorded_offset=-5)
    future = _memory("future", recorded_offset=2)
    with engine.begin() as conn:
        store.record_institutional_memory(conn, visible)
        store.record_institutional_memory(conn, future)
        store.record_failure_archive_entry(conn, _failure("visible", recorded_offset=-4))
        store.record_failure_archive_entry(conn, _failure("future", recorded_offset=3))
        record_crisis_regime_archive_entry(
            conn,
            store=store,
            entry=_crisis("visible-crisis", recorded_offset=-3),
        )
        record_crisis_regime_archive_entry(
            conn,
            store=store,
            entry=_crisis("future-crisis", recorded_offset=4),
        )

    with engine.begin() as conn:
        context = load_institutional_experience_context(
            conn,
            store=store,
            query=InstitutionalExperienceQuery(as_of_utc=T0),
        )

    assert context.decision_context.matched_memory_ids == ("visible",)
    assert tuple(row.failure_id for row in context.failure_history.entries) == (
        "failure-visible",
    )
    assert tuple(row.archive_id for row in context.crisis_regime_entries) == (
        "visible-crisis",
    )
