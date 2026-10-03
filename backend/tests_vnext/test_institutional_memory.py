from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.institutional_memory import (
    CounterfactualReplayRecord,
    ExperienceCoverage,
    FailureArchiveEntry,
    InstitutionalMemoryRecord,
    PnlAttributionComponent,
    PnlAttributionRecord,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _component(category: str, amount: float) -> PnlAttributionComponent:
    return PnlAttributionComponent(category=category, amount_usd=amount)


def _attribution(**overrides: object) -> PnlAttributionRecord:
    kwargs: dict[str, object] = {
        "attribution_id": "attr-1",
        "firm_id": "aether",
        "mechanism_id": "trend",
        "playbook_id": "pb-trend",
        "playbook_version": "v1",
        "route_id": "btc:1h:trend",
        "asset_id": "btc",
        "horizon": "1h",
        "side": "long",
        "regime_id": "trend-up",
        "trade_id": "trade-1",
        "configuration_hash": "cfg-1",
        "net_pnl_usd": 75.0,
        "components": (
            _component("alpha", 100.0),
            _component("fees", -10.0),
            _component("slippage", -15.0),
        ),
        "attributed_at_utc": T0,
        "source_record_ids": ("fill-1", "journal-1"),
    }
    kwargs.update(overrides)
    return PnlAttributionRecord(**kwargs)


def _memory(**overrides: object) -> InstitutionalMemoryRecord:
    kwargs: dict[str, object] = {
        "memory_id": "memory-1",
        "trade_id": "trade-1",
        "route_id": "btc:1h:trend",
        "playbook_id": "pb-trend",
        "playbook_version": "v1",
        "configuration_hash": "cfg-1",
        "market_state_ref": "market-state-1",
        "information_state_ref": "information-state-1",
        "signal_ref": "signal-1",
        "decision_ref": "decision-1",
        "expected_outcome_ref": "expected-1",
        "actual_outcome_ref": "actual-1",
        "execution_quality_ref": "execution-quality-1",
        "risk_state_ref": "risk-state-1",
        "success_failure_reason": "clean continuation",
        "lesson": "trend continuation held after verified trigger",
        "future_relevance": ("trend_up", "btc"),
        "occurred_at_utc": T0,
        "recorded_at_utc": T0 + timedelta(minutes=1),
        "source_record_ids": ("trade-1", "fill-1"),
    }
    kwargs.update(overrides)
    return InstitutionalMemoryRecord(**kwargs)


def test_pnl_attribution_reconciles_without_unexplained_residual() -> None:
    record = _attribution()
    assert sum(row.amount_usd for row in record.components) == record.net_pnl_usd


def test_pnl_attribution_rejects_residual_duplicate_and_invalid_category() -> None:
    with pytest.raises(ValueError, match="no unexplained residual"):
        _attribution(net_pnl_usd=74.0)

    with pytest.raises(ValueError, match="duplicate P&L attribution category"):
        _attribution(
            components=(
                _component("alpha", 50.0),
                _component("alpha", 25.0),
            )
        )

    with pytest.raises(ValueError, match="invalid P&L attribution category"):
        _component("mystery", 1.0)


def test_pnl_attribution_rejects_boolean_numeric_and_noncanonical_asset() -> None:
    with pytest.raises(ValueError, match="amount_usd must be finite numeric"):
        _component("fees", True)

    with pytest.raises(ValueError, match="asset_id must be canonical lowercase"):
        _attribution(asset_id="BTC")


def test_memory_preserves_complete_state_chain_and_immutable_lineage() -> None:
    record = _memory()
    assert record.market_state_ref == "market-state-1"
    assert record.information_state_ref == "information-state-1"
    assert record.signal_ref == "signal-1"
    assert record.decision_ref == "decision-1"
    assert record.expected_outcome_ref == "expected-1"
    assert record.actual_outcome_ref == "actual-1"
    assert record.execution_quality_ref == "execution-quality-1"
    assert record.risk_state_ref == "risk-state-1"
    assert record.future_relevance == ("trend_up", "btc")


def test_memory_rejects_mutable_lineage_and_reversed_time() -> None:
    with pytest.raises(ValueError, match="future_relevance must be an immutable tuple"):
        _memory(future_relevance=["trend_up"])

    with pytest.raises(ValueError, match="memory cannot be recorded before occurrence"):
        _memory(recorded_at_utc=T0 - timedelta(seconds=1))


@pytest.mark.parametrize(
    "category",
    (
        "losing_mechanism_false_break",
        "abnormal_slippage_spread_widening",
        "failed_hedge_correlation_convergence",
        "rejected_duplicated_ambiguous_orders",
        "stale_malformed_data",
        "model_assumption_failure",
        "operational_incident_recovery",
    ),
)
def test_failure_archive_accepts_canonical_categories(category: str) -> None:
    entry = FailureArchiveEntry(
        failure_id=f"failure-{category}",
        memory_id="memory-1",
        trade_id="trade-1",
        category=category,
        reason="observed failure",
        recovery_lesson="retain as scar tissue",
        recorded_at_utc=T0,
        source_record_ids=("memory-1",),
    )
    assert entry.category == category


def test_counterfactual_replay_cannot_overwrite_evidence_semantics() -> None:
    replay = CounterfactualReplayRecord(
        replay_id="replay-1",
        original_memory_id="memory-1",
        variation_keys=("stop", "no_trade"),
        hypothetical_result_ref="hypothetical-result-1",
        created_at_utc=T0,
    )
    assert replay.hypothetical is True
    assert replay.independent_evidence_credit is False

    with pytest.raises(
        ValueError,
        match="cannot receive independent evidence credit",
    ):
        CounterfactualReplayRecord(
            replay_id="replay-2",
            original_memory_id="memory-1",
            variation_keys=("target",),
            hypothetical_result_ref="hypothetical-result-2",
            created_at_utc=T0,
            independent_evidence_credit=True,
        )


def test_experience_coverage_is_descriptive_not_threshold_inventing() -> None:
    coverage = ExperienceCoverage(
        historical_years=3.5,
        unique_regimes_crises=8,
        event_categories=12,
        asset_event_combinations=25,
        execution_failure_scenarios=7,
        correlation_stress_scenarios=4,
        unique_market_state_clusters=19,
        forward_paper_days=90,
        forward_paper_trades=140,
        historical_forward_gaps=3,
    )
    assert coverage.forward_paper_days == 90

    with pytest.raises(
        ValueError,
        match="historical_forward_gaps must be a nonnegative integer",
    ):
        ExperienceCoverage(
            historical_years=1.0,
            unique_regimes_crises=0,
            event_categories=0,
            asset_event_combinations=0,
            execution_failure_scenarios=0,
            correlation_stress_scenarios=0,
            unique_market_state_clusters=0,
            forward_paper_days=0,
            forward_paper_trades=0,
            historical_forward_gaps=-1,
        )
