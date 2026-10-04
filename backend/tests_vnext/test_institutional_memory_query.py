from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.institutional_analogs import HistoricalDecisionContextQuery
from aether_vnext.institutional_memory import InstitutionalMemoryRecord
from aether_vnext.institutional_memory_query import (
    load_historical_decision_context,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 14, 0, tzinfo=UTC)


def _memory(
    memory_id: str,
    *,
    route_id: str = "btc:1h:trend",
    tags: tuple[str, ...] = ("trend_up", "btc"),
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
        lesson="retain observed lesson",
        future_relevance=tags,
        occurred_at_utc=T0 + timedelta(minutes=recorded_offset - 1),
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(f"source-{memory_id}",),
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def test_durable_query_blocks_future_recorded_memory_before_retrieval() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_institutional_memory(conn, _memory("old", recorded_offset=-4))
        store.record_institutional_memory(conn, _memory("future", recorded_offset=1))

    with engine.begin() as conn:
        context = load_historical_decision_context(
            conn,
            store=store,
            query=HistoricalDecisionContextQuery(as_of_utc=T0),
        )

    assert context.matched_memory_ids == ("old",)
    assert context.research_only is True
    assert context.trade_influence_allowed is False


def test_durable_query_applies_lineage_then_relevance_without_policy_weights() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_institutional_memory(
            conn,
            _memory("match", tags=("trend_up", "btc"), recorded_offset=-2),
        )
        store.record_institutional_memory(
            conn,
            _memory("irrelevant", tags=("range", "btc"), recorded_offset=-1),
        )
        store.record_institutional_memory(
            conn,
            _memory("wrong-route", route_id="eth:1h:trend", recorded_offset=-3),
        )

    query = HistoricalDecisionContextQuery(
        as_of_utc=T0,
        route_id="btc:1h:trend",
        playbook_id="pb-trend",
        playbook_version="v1",
        configuration_hash="cfg-1",
        relevance_tags=("trend_up",),
        limit=5,
    )
    with engine.begin() as conn:
        context = load_historical_decision_context(
            conn,
            store=store,
            query=query,
        )

    assert context.matched_memory_ids == ("match",)
