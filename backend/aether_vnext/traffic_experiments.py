"""Configuration-isolated traffic experiments for AETHER vNext.

Part IV P9 permits controlled Scout/Sniper/Clerk policy experiments while forbidding
trade-count optimization and evidence contamination. Shadow comparisons are diagnostic
counterfactuals only and can never create an OrderIntent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
from typing import Iterable

from aether_vnext.evidence import EvidenceWindow


class TrafficChangeFamily(StrEnum):
    SCOUT = "SCOUT"
    SNIPER = "SNIPER"
    CLERK = "CLERK"


class TrafficStage(StrEnum):
    UNIVERSE = "UNIVERSE"
    WATCH = "WATCH"
    FIRE = "FIRE"
    SIZE = "SIZE"
    READY = "READY"
    ORDER = "ORDER"
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class TrafficExperiment:
    experiment_id: str
    change_family: TrafficChangeFamily
    control_configuration_hash: str
    treatment_configuration_hash: str
    hypothesis: str
    owner: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "experiment_id",
            "control_configuration_hash",
            "treatment_configuration_hash",
            "hypothesis",
            "owner",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")
        if (
            self.control_configuration_hash
            == self.treatment_configuration_hash
        ):
            raise ValueError(
                "control and treatment configuration_hash must differ"
            )


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    shadow_comparison_id: str
    experiment_id: str
    opportunity_id: str
    current_configuration_hash: str
    prior_configuration_hash: str
    would_pass_under_prior_policy: bool
    evaluated_at_utc: datetime
    order_created: bool = False

    def __post_init__(self) -> None:
        for name in (
            "shadow_comparison_id",
            "experiment_id",
            "opportunity_id",
            "current_configuration_hash",
            "prior_configuration_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.evaluated_at_utc.tzinfo is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        if self.order_created:
            raise ValueError("shadow comparison cannot create an order")
        if self.current_configuration_hash == self.prior_configuration_hash:
            raise ValueError("shadow comparison requires distinct configurations")


@dataclass(frozen=True, slots=True)
class TrafficObservation:
    opportunity_id: str
    configuration_hash: str
    stage: TrafficStage
    dwell_ms: int
    wait_or_deferred: bool = False
    terminal_reject: bool = False
    first_killed_by: str | None = None
    first_kill_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.opportunity_id or not self.configuration_hash:
            raise ValueError("opportunity_id and configuration_hash are required")
        if int(self.dwell_ms) < 0:
            raise ValueError("dwell_ms cannot be negative")
        if self.wait_or_deferred and self.terminal_reject:
            raise ValueError("WAIT/DEFER cannot also be terminal rejection")
        if self.terminal_reject and not str(self.first_killed_by or "").strip():
            raise ValueError("terminal rejection requires first_killed_by")
        if self.terminal_reject and not str(self.first_kill_reason or "").strip():
            raise ValueError("terminal rejection requires first_kill_reason")


def summarize_traffic(
    observations: Iterable[TrafficObservation],
    *,
    configuration_hash: str,
) -> dict[str, object]:
    rows = tuple(observations)
    if any(row.configuration_hash != configuration_hash for row in rows):
        raise ValueError("traffic summary cannot mix configuration_hash cohorts")

    stage_counts = {stage.value: 0 for stage in TrafficStage}
    dwell: dict[str, list[int]] = {stage.value: [] for stage in TrafficStage}
    first_killers: dict[str, int] = {}
    wait_count = 0
    reject_count = 0

    for row in rows:
        stage_counts[row.stage.value] += 1
        dwell[row.stage.value].append(int(row.dwell_ms))
        if row.wait_or_deferred:
            wait_count += 1
        if row.terminal_reject:
            reject_count += 1
            key = f"{row.first_killed_by}:{row.first_kill_reason}"
            first_killers[key] = first_killers.get(key, 0) + 1

    average_dwell_ms = {
        stage: (
            sum(values) / len(values)
            if values
            else None
        )
        for stage, values in dwell.items()
    }
    return {
        "configuration_hash": configuration_hash,
        "stage_counts": stage_counts,
        "wait_deferred_count": wait_count,
        "terminal_reject_count": reject_count,
        "first_killer_distribution": dict(sorted(first_killers.items())),
        "average_dwell_ms": average_dwell_ms,
        "target_trade_count": None,
    }


def assert_experiment_evidence_isolated(
    experiment: TrafficExperiment,
    *,
    control_windows: Iterable[EvidenceWindow],
    treatment_windows: Iterable[EvidenceWindow],
) -> None:
    control = tuple(control_windows)
    treatment = tuple(treatment_windows)

    if any(
        row.configuration_hash != experiment.control_configuration_hash
        for row in control
    ):
        raise ValueError("control evidence contains wrong configuration_hash")
    if any(
        row.configuration_hash != experiment.treatment_configuration_hash
        for row in treatment
    ):
        raise ValueError("treatment evidence contains wrong configuration_hash")

    control_ids = {
        trade_id
        for row in control
        for trade_id in row.immutable_trade_ids
    }
    treatment_ids = {
        trade_id
        for row in treatment
        for trade_id in row.immutable_trade_ids
    }
    if control_ids & treatment_ids:
        raise ValueError("control/treatment evidence trade identity overlaps")


@dataclass(frozen=True, slots=True)
class TrafficPromotionEvidence:
    control_oos_net_expectancy_usd: float
    treatment_oos_net_expectancy_usd: float
    drawdown_acceptable: bool | None
    cost_acceptable: bool | None
    cluster_acceptable: bool | None
    control_oos: bool
    treatment_oos: bool

    def __post_init__(self) -> None:
        for name in (
            "control_oos_net_expectancy_usd",
            "treatment_oos_net_expectancy_usd",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class TrafficPromotionAssessment:
    promotion_eligible: bool
    expectancy_improved: bool
    unresolved_rules: tuple[str, ...]
    blocking_reasons: tuple[str, ...]


def assess_traffic_promotion(
    evidence: TrafficPromotionEvidence,
) -> TrafficPromotionAssessment:
    unresolved: list[str] = []
    blocked: list[str] = []

    if not evidence.control_oos or not evidence.treatment_oos:
        blocked.append("oos_evidence_required")

    improved = (
        float(evidence.treatment_oos_net_expectancy_usd)
        > float(evidence.control_oos_net_expectancy_usd)
    )
    if not improved:
        blocked.append("treatment_oos_expectancy_not_improved")

    for name in (
        "drawdown_acceptable",
        "cost_acceptable",
        "cluster_acceptable",
    ):
        value = getattr(evidence, name)
        if value is None:
            unresolved.append(f"{name}_criterion_unbound")
        elif value is False:
            blocked.append(f"{name}_failed")

    return TrafficPromotionAssessment(
        promotion_eligible=not unresolved and not blocked,
        expectancy_improved=improved,
        unresolved_rules=tuple(unresolved),
        blocking_reasons=tuple(blocked),
    )
