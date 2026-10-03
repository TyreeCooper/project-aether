"""Read-only daily/weekly Firm review surfaces for AETHER vNext Phase 14.

These projections implement the canonical C9 operating cadence. They summarize
already-recorded Firm state and research evidence; they have no mutation or
execution authority and must not promote routes, alter Risk, or reset Governor.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Mapping, Sequence


def _utc_timestamp(name: str, value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _operator_timestamp(value: datetime, timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("operator_timezone must be a valid IANA timezone") from exc
    return value.astimezone(zone).isoformat()


def _mapping_tuple(
    name: str,
    values: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of mappings")
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} entries must be mappings")
        rows.append(dict(value))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class DailyFirmReviewInput:
    review_timestamp: datetime
    operator_timezone: str
    market_event_regimes: Sequence[Mapping[str, Any]]
    material_news_events_and_analogs: Sequence[Mapping[str, Any]]
    opportunities_and_dispositions: Sequence[Mapping[str, Any]]
    trades_opened_closed_duration: Sequence[Mapping[str, Any]]
    pnl_and_cost_drag: Mapping[str, Any]
    blocked_opportunities: Sequence[Mapping[str, Any]]
    route_evidence_increments: Sequence[Mapping[str, Any]]
    abnormal_execution_reconciliation: Sequence[Mapping[str, Any]]
    risk_utilization_and_cluster_exposure: Mapping[str, Any]
    route_state_changes: Sequence[Mapping[str, Any]]

    def __post_init__(self) -> None:
        _utc_timestamp("review_timestamp", self.review_timestamp)
        if (
            not isinstance(self.operator_timezone, str)
            or not self.operator_timezone
            or self.operator_timezone != self.operator_timezone.strip()
        ):
            raise ValueError("operator_timezone must be canonical text")
        try:
            ZoneInfo(self.operator_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "operator_timezone must be a valid IANA timezone"
            ) from exc
        for name in (
            "market_event_regimes",
            "material_news_events_and_analogs",
            "opportunities_and_dispositions",
            "trades_opened_closed_duration",
            "blocked_opportunities",
            "route_evidence_increments",
            "abnormal_execution_reconciliation",
            "route_state_changes",
        ):
            _mapping_tuple(name, getattr(self, name))
        if not isinstance(self.pnl_and_cost_drag, Mapping):
            raise ValueError("pnl_and_cost_drag must be a mapping")
        if not isinstance(self.risk_utilization_and_cluster_exposure, Mapping):
            raise ValueError(
                "risk_utilization_and_cluster_exposure must be a mapping"
            )


@dataclass(frozen=True, slots=True)
class WeeklyFirmResearchReviewInput:
    review_timestamp: datetime
    operator_timezone: str
    route_comparisons: Sequence[Mapping[str, Any]]
    mechanism_comparison_and_concentration: Sequence[Mapping[str, Any]]
    regime_dependency: Sequence[Mapping[str, Any]]
    event_conditioned_performance: Sequence[Mapping[str, Any]]
    evidence_sufficiency_and_uncertainty: Sequence[Mapping[str, Any]]
    cost_sensitivity_and_execution_model_error: Sequence[Mapping[str, Any]]
    hypothesis_experiment_queue: Sequence[Mapping[str, Any]]
    bench_candidates_and_failure_reasons: Sequence[Mapping[str, Any]]
    data_and_experience_coverage_gaps: Sequence[Mapping[str, Any]]

    def __post_init__(self) -> None:
        _utc_timestamp("review_timestamp", self.review_timestamp)
        if (
            not isinstance(self.operator_timezone, str)
            or not self.operator_timezone
            or self.operator_timezone != self.operator_timezone.strip()
        ):
            raise ValueError("operator_timezone must be canonical text")
        try:
            ZoneInfo(self.operator_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "operator_timezone must be a valid IANA timezone"
            ) from exc
        for name in (
            "route_comparisons",
            "mechanism_comparison_and_concentration",
            "regime_dependency",
            "event_conditioned_performance",
            "evidence_sufficiency_and_uncertainty",
            "cost_sensitivity_and_execution_model_error",
            "hypothesis_experiment_queue",
            "bench_candidates_and_failure_reasons",
            "data_and_experience_coverage_gaps",
        ):
            _mapping_tuple(name, getattr(self, name))


def _authority() -> dict[str, object]:
    return {
        "read_only": True,
        "execution_permission": False,
        "may_create_orders": False,
        "may_mutate_route_state": False,
        "may_mutate_risk": False,
        "may_reset_governor": False,
        "may_award_independent_evidence_credit": False,
    }


def build_daily_firm_review(
    review: DailyFirmReviewInput,
) -> dict[str, object]:
    """Build the canonical C9.2 daily review projection."""
    return {
        "review_type": "daily_firm_review",
        "review_timestamp": _utc_timestamp(
            "review_timestamp",
            review.review_timestamp,
        ).isoformat(),
        "operator_timezone": review.operator_timezone,
        "review_timestamp_local": _operator_timestamp(
            review.review_timestamp,
            review.operator_timezone,
        ),
        "authority": _authority(),
        "market_event_regimes": list(
            _mapping_tuple("market_event_regimes", review.market_event_regimes)
        ),
        "material_news_events_and_analogs": list(
            _mapping_tuple(
                "material_news_events_and_analogs",
                review.material_news_events_and_analogs,
            )
        ),
        "opportunities_and_dispositions": list(
            _mapping_tuple(
                "opportunities_and_dispositions",
                review.opportunities_and_dispositions,
            )
        ),
        "trades_opened_closed_duration": list(
            _mapping_tuple(
                "trades_opened_closed_duration",
                review.trades_opened_closed_duration,
            )
        ),
        "pnl_and_cost_drag": dict(review.pnl_and_cost_drag),
        "blocked_opportunities": list(
            _mapping_tuple("blocked_opportunities", review.blocked_opportunities)
        ),
        "route_evidence_increments": list(
            _mapping_tuple(
                "route_evidence_increments",
                review.route_evidence_increments,
            )
        ),
        "abnormal_execution_reconciliation": list(
            _mapping_tuple(
                "abnormal_execution_reconciliation",
                review.abnormal_execution_reconciliation,
            )
        ),
        "risk_utilization_and_cluster_exposure": dict(
            review.risk_utilization_and_cluster_exposure
        ),
        "route_state_changes": list(
            _mapping_tuple("route_state_changes", review.route_state_changes)
        ),
    }


def build_weekly_firm_research_review(
    review: WeeklyFirmResearchReviewInput,
) -> dict[str, object]:
    """Build the canonical C9.3 weekly research review projection."""
    return {
        "review_type": "weekly_firm_research_review",
        "review_timestamp": _utc_timestamp(
            "review_timestamp",
            review.review_timestamp,
        ).isoformat(),
        "operator_timezone": review.operator_timezone,
        "review_timestamp_local": _operator_timestamp(
            review.review_timestamp,
            review.operator_timezone,
        ),
        "authority": _authority(),
        "promotion_policy": {
            "automatic_promotion": False,
            "route_comparison_is_descriptive": True,
        },
        "route_comparisons": list(
            _mapping_tuple("route_comparisons", review.route_comparisons)
        ),
        "mechanism_comparison_and_concentration": list(
            _mapping_tuple(
                "mechanism_comparison_and_concentration",
                review.mechanism_comparison_and_concentration,
            )
        ),
        "regime_dependency": list(
            _mapping_tuple("regime_dependency", review.regime_dependency)
        ),
        "event_conditioned_performance": list(
            _mapping_tuple(
                "event_conditioned_performance",
                review.event_conditioned_performance,
            )
        ),
        "evidence_sufficiency_and_uncertainty": list(
            _mapping_tuple(
                "evidence_sufficiency_and_uncertainty",
                review.evidence_sufficiency_and_uncertainty,
            )
        ),
        "cost_sensitivity_and_execution_model_error": list(
            _mapping_tuple(
                "cost_sensitivity_and_execution_model_error",
                review.cost_sensitivity_and_execution_model_error,
            )
        ),
        "hypothesis_experiment_queue": list(
            _mapping_tuple(
                "hypothesis_experiment_queue",
                review.hypothesis_experiment_queue,
            )
        ),
        "bench_candidates_and_failure_reasons": list(
            _mapping_tuple(
                "bench_candidates_and_failure_reasons",
                review.bench_candidates_and_failure_reasons,
            )
        ),
        "data_and_experience_coverage_gaps": list(
            _mapping_tuple(
                "data_and_experience_coverage_gaps",
                review.data_and_experience_coverage_gaps,
            )
        ),
    }
