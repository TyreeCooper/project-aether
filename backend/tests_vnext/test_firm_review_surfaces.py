from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.firm_review_surfaces import (
    DailyFirmReviewInput,
    WeeklyFirmResearchReviewInput,
    build_daily_firm_review,
    build_weekly_firm_research_review,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 17, 30, tzinfo=UTC)


def test_daily_review_contains_every_canonical_c9_2_section() -> None:
    review = DailyFirmReviewInput(
        review_timestamp=T0,
        operator_timezone="America/New_York",
        market_event_regimes=({"asset_id": "btc", "regime": "risk_off"},),
        material_news_events_and_analogs=(
            {"event_id": "evt-1", "analog_run_id": "analog-1"},
        ),
        opportunities_and_dispositions=(
            {"opportunity_id": "opp-1", "disposition": "blocked"},
        ),
        trades_opened_closed_duration=(
            {"trade_id": "trade-1", "duration_s": 1200},
        ),
        pnl_and_cost_drag={
            "gross_pnl_usd": 100.0,
            "net_pnl_usd": 80.0,
            "cost_drag_usd": 20.0,
        },
        blocked_opportunities=(
            {"opportunity_id": "opp-1", "blocker_reason": "risk_limit"},
        ),
        route_evidence_increments=(
            {"route_id": "btc:1h:trend", "n_increment": 1},
        ),
        abnormal_execution_reconciliation=(
            {"event_id": "exec-1", "kind": "spread_widening"},
        ),
        risk_utilization_and_cluster_exposure={
            "portfolio_stop_risk_usd": 50.0,
            "open_clusters": ["crypto"],
        },
        route_state_changes=(
            {"route_id": "btc:1h:trend", "from": "CANDIDATE", "to": "KEEP_PROBATION"},
        ),
    )

    result = build_daily_firm_review(review)

    assert result["review_type"] == "daily_firm_review"
    assert result["review_timestamp"] == T0.isoformat()
    assert result["authority"]["read_only"] is True
    assert result["authority"]["execution_permission"] is False
    assert result["authority"]["may_mutate_route_state"] is False
    assert result["pnl_and_cost_drag"]["net_pnl_usd"] == 80.0
    assert result["trades_opened_closed_duration"][0]["duration_s"] == 1200


def test_weekly_review_contains_every_canonical_c9_3_section() -> None:
    review = WeeklyFirmResearchReviewInput(
        review_timestamp=T0,
        operator_timezone="America/New_York",
        route_comparisons=({"route_id": "btc:1h:trend", "n": 30},),
        mechanism_comparison_and_concentration=(
            {"mechanism_id": "trend", "share": 0.6},
        ),
        regime_dependency=({"regime_id": "risk_off", "net_pnl_usd": -10.0},),
        event_conditioned_performance=(
            {"event_type": "scheduled_macro_surprise", "sample_count": 5},
        ),
        evidence_sufficiency_and_uncertainty=(
            {"route_id": "btc:1h:trend", "status": "insufficient"},
        ),
        cost_sensitivity_and_execution_model_error=(
            {"route_id": "btc:1h:trend", "plus25_expectancy_usd": 2.0},
        ),
        hypothesis_experiment_queue=(
            {"experiment_id": "exp-1", "state": "queued"},
        ),
        bench_candidates_and_failure_reasons=(
            {"route_id": "btc:1h:trend", "reason": "stop_grind"},
        ),
        data_and_experience_coverage_gaps=(
            {"gap": "forward_paper_days", "remaining": 20},
        ),
    )

    result = build_weekly_firm_research_review(review)

    assert result["review_type"] == "weekly_firm_research_review"
    assert result["promotion_policy"]["automatic_promotion"] is False
    assert result["promotion_policy"]["route_comparison_is_descriptive"] is True
    assert result["authority"]["may_award_independent_evidence_credit"] is False
    assert result["event_conditioned_performance"][0]["sample_count"] == 5


def test_review_surfaces_require_traceable_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="review_timestamp must be timezone-aware"):
        DailyFirmReviewInput(
            review_timestamp=datetime(2026, 9, 29, 17, 30),
            operator_timezone="America/New_York",
            market_event_regimes=(),
            material_news_events_and_analogs=(),
            opportunities_and_dispositions=(),
            trades_opened_closed_duration=(),
            pnl_and_cost_drag={},
            blocked_opportunities=(),
            route_evidence_increments=(),
            abnormal_execution_reconciliation=(),
            risk_utilization_and_cluster_exposure={},
            route_state_changes=(),
        )
