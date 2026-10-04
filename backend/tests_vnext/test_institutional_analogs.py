from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.institutional_analogs import (
    HistoricalDecisionContext,
    HistoricalDecisionContextQuery,
    retrieve_historical_decision_context,
)
from aether_vnext.institutional_memory import InstitutionalMemoryRecord


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)


def _memory(
    memory_id: str,
    *,
    route_id: str = "btc:1h:trend",
    playbook_id: str = "pb-trend",
    playbook_version: str = "v1",
    configuration_hash: str = "cfg-1",
    future_relevance: tuple[str, ...] = ("trend_up", "btc"),
    occurred_offset: int = -10,
    recorded_offset: int = -9,
) -> InstitutionalMemoryRecord:
    return InstitutionalMemoryRecord(
        memory_id=memory_id,
        trade_id=f"trade-{memory_id}",
        route_id=route_id,
        playbook_id=playbook_id,
        playbook_version=playbook_version,
        configuration_hash=configuration_hash,
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
        future_relevance=future_relevance,
        occurred_at_utc=T0 + timedelta(minutes=occurred_offset),
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(f"source-{memory_id}",),
    )


def test_retrieval_uses_recorded_time_to_prevent_lookahead() -> None:
    query = HistoricalDecisionContextQuery(as_of_utc=T0)
    visible = _memory("visible")
    unavailable = _memory(
        "unavailable",
        occurred_offset=-20,
        recorded_offset=1,
    )

    context = retrieve_historical_decision_context(
        query=query,
        memories=(unavailable, visible),
    )

    assert context.matched_memory_ids == ("visible",)
    assert context.research_only is True
    assert context.trade_influence_allowed is False
    assert context.independent_evidence_credit is False


def test_explicit_lineage_filters_do_not_invent_similarity_policy() -> None:
    query = HistoricalDecisionContextQuery(
        as_of_utc=T0,
        route_id="btc:1h:trend",
        playbook_id="pb-trend",
        playbook_version="v1",
        configuration_hash="cfg-1",
    )
    exact = _memory("exact")
    wrong_route = _memory("route", route_id="eth:1h:trend")
    wrong_version = _memory("version", playbook_version="v2")
    wrong_config = _memory("config", configuration_hash="cfg-2")

    context = retrieve_historical_decision_context(
        query=query,
        memories=(wrong_route, wrong_version, wrong_config, exact),
    )

    assert context.matched_memory_ids == ("exact",)


def test_relevance_filter_is_overlap_only_and_results_are_deterministic() -> None:
    query = HistoricalDecisionContextQuery(
        as_of_utc=T0,
        relevance_tags=("trend_up",),
        limit=2,
    )
    older = _memory("older", recorded_offset=-8)
    newest = _memory("newest", recorded_offset=-2)
    middle = _memory("middle", recorded_offset=-5)
    irrelevant = _memory(
        "irrelevant",
        future_relevance=("range", "btc"),
        recorded_offset=-1,
    )

    context = retrieve_historical_decision_context(
        query=query,
        memories=(older, irrelevant, newest, middle),
    )

    assert context.matched_memory_ids == ("newest", "middle")


def test_query_and_result_keep_research_only_boundary() -> None:
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        HistoricalDecisionContextQuery(as_of_utc=T0, limit=0)

    with pytest.raises(
        ValueError,
        match="historical decision context cannot influence trades",
    ):
        HistoricalDecisionContext(
            as_of_utc=T0,
            matched_memory_ids=(),
            matched_trade_ids=(),
            matched_recorded_at_utc=(),
            trade_influence_allowed=True,
        )

    with pytest.raises(
        ValueError,
        match="cannot receive independent evidence credit",
    ):
        HistoricalDecisionContext(
            as_of_utc=T0,
            matched_memory_ids=(),
            matched_trade_ids=(),
            matched_recorded_at_utc=(),
            independent_evidence_credit=True,
        )
