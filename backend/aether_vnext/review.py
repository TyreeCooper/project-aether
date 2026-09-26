"""Deterministic Firm Review evidence gates for AETHER vNext.

This module implements the source-bound v3.1 / v5 Review bars. Review remains the
owner of evidence state. The gate engine validates whether a proposed verdict is
legally supported by the evidence; it does not mutate money, positions, orders, or
policy risk fractions.

The source phrase for the stop-grind BENCH arm uses
"|net| approximately initial_stop_risk" without binding a tolerance. That boolean
must therefore be supplied only by a separately bound rule. None means unresolved
and cannot silently trigger BENCH.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from aether_vnext.freeze import EvidenceState


CUT_SIZE_FLOOR_FRACTION = 0.0025
FALSE_DISCOVERY_ROUTE_THRESHOLD = 50


@dataclass(frozen=True, slots=True)
class ReviewGateInput:
    evidence_id: str
    n_closed: int
    fold_expectancy_after_plus25_cost: tuple[float, ...]
    expectancy_ci_lower: float | None
    net_expectancy_after_costs: float
    profit_factor: float
    stop_rate: float
    baseline_not_worse: bool
    folds_chronological: bool
    integrity_clear: bool
    current_route_risk_fraction: float
    radar_eligible_routes: int
    prior_evidence_state: EvidenceState
    false_discovery_extra_fold_completed: bool = False
    multi_day_fx: bool = False
    carry_model_present: bool = True
    last10_stop_grind_confirmed: bool | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id is required")
        if int(self.n_closed) < 0:
            raise ValueError("n_closed cannot be negative")
        if int(self.radar_eligible_routes) < 0:
            raise ValueError("radar_eligible_routes cannot be negative")
        if not 0.0 <= float(self.stop_rate) <= 1.0:
            raise ValueError("stop_rate must be in [0,1]")
        if float(self.current_route_risk_fraction) <= 0.0:
            raise ValueError("current_route_risk_fraction must be positive")
        for name, value in (
            ("net_expectancy_after_costs", self.net_expectancy_after_costs),
            ("profit_factor", self.profit_factor),
            ("current_route_risk_fraction", self.current_route_risk_fraction),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.expectancy_ci_lower is not None and not math.isfinite(
            float(self.expectancy_ci_lower)
        ):
            raise ValueError("expectancy_ci_lower must be finite")
        for value in self.fold_expectancy_after_plus25_cost:
            if not math.isfinite(float(value)):
                raise ValueError("fold expectancy values must be finite")


@dataclass(frozen=True, slots=True)
class ReviewGateAssessment:
    evidence_id: str
    n_closed: int
    fold_count: int
    positive_plus25_fold_count: int
    probation_keep_eligible: bool
    trusted_keep_eligible: bool
    mandatory_state: EvidenceState | None
    cut_size_fraction: float | None
    reasons: tuple[str, ...]
    unresolved_rules: tuple[str, ...]
    net_expectancy_after_costs: float
    profit_factor: float
    stop_rate: float


def assess_review_gates(
    gate: ReviewGateInput,
) -> ReviewGateAssessment:
    folds = tuple(
        float(value)
        for value in gate.fold_expectancy_after_plus25_cost
    )
    fold_count = len(folds)
    positive_plus25 = sum(1 for value in folds if value > 0.0)

    unresolved: list[str] = []
    bench_reasons: list[str] = []
    cut_reasons: list[str] = []

    if gate.last10_stop_grind_confirmed is True:
        bench_reasons.append("last10_stop_grind_8_of_10")
    elif gate.last10_stop_grind_confirmed is None:
        unresolved.append("stop_grind_approximation_tolerance_unbound")

    if (
        gate.n_closed >= 10
        and float(gate.net_expectancy_after_costs) < 0.0
    ):
        bench_reasons.append("n10_negative_expectancy_after_costs")
    if gate.multi_day_fx and not gate.carry_model_present:
        bench_reasons.append("multi_day_fx_missing_carry_model")

    if gate.n_closed >= 10 and float(gate.stop_rate) >= 0.60:
        cut_reasons.append("n10_stop_rate_ge_0_60")
    if (
        gate.n_closed >= 10
        and float(gate.net_expectancy_after_costs) <= 0.0
    ):
        cut_reasons.append("n10_expectancy_le_0")

    probation_keep = bool(
        gate.n_closed >= 15
        and fold_count >= 3
        and gate.expectancy_ci_lower is not None
        and float(gate.expectancy_ci_lower) >= 0.0
        and gate.folds_chronological
        and gate.integrity_clear
    )

    false_discovery_ok = True
    if gate.radar_eligible_routes > FALSE_DISCOVERY_ROUTE_THRESHOLD:
        false_discovery_ok = bool(
            gate.prior_evidence_state is EvidenceState.KEEP_PROBATION
            and gate.false_discovery_extra_fold_completed
        )

    trusted_keep = bool(
        gate.n_closed >= 30
        and fold_count >= 4
        and positive_plus25 >= 3
        and float(gate.profit_factor) > 1.20
        and float(gate.stop_rate) < 0.55
        and gate.baseline_not_worse
        and gate.folds_chronological
        and gate.integrity_clear
        and false_discovery_ok
    )

    mandatory: EvidenceState | None = None
    cut_fraction: float | None = None
    reasons: list[str] = []

    # The BENCH negative-expectancy arm is stricter than CUT_SIZE's <=0 arm and
    # therefore wins when both are true. This preserves the source thresholds.
    if bench_reasons:
        mandatory = EvidenceState.BENCH
        reasons.extend(bench_reasons)
    elif cut_reasons:
        mandatory = EvidenceState.CUT_SIZE
        cut_fraction = max(
            CUT_SIZE_FLOOR_FRACTION,
            float(gate.current_route_risk_fraction) / 2.0,
        )
        reasons.extend(cut_reasons)

    if gate.radar_eligible_routes > FALSE_DISCOVERY_ROUTE_THRESHOLD:
        if not false_discovery_ok:
            reasons.append("false_discovery_control_unsatisfied")

    if not gate.folds_chronological:
        reasons.append("folds_not_chronological")
    if not gate.integrity_clear:
        reasons.append("integrity_not_clear")

    return ReviewGateAssessment(
        evidence_id=gate.evidence_id,
        n_closed=gate.n_closed,
        fold_count=fold_count,
        positive_plus25_fold_count=positive_plus25,
        probation_keep_eligible=probation_keep,
        trusted_keep_eligible=trusted_keep,
        mandatory_state=mandatory,
        cut_size_fraction=cut_fraction,
        reasons=tuple(dict.fromkeys(reasons)),
        unresolved_rules=tuple(dict.fromkeys(unresolved)),
        net_expectancy_after_costs=float(
            gate.net_expectancy_after_costs
        ),
        profit_factor=float(gate.profit_factor),
        stop_rate=float(gate.stop_rate),
    )


def validate_review_verdict(
    assessment: ReviewGateAssessment,
    proposed_state: EvidenceState,
) -> None:
    """Raise when Review's proposed evidence state violates frozen bars."""
    mandatory = assessment.mandatory_state
    if mandatory is not None:
        if proposed_state is not mandatory:
            raise ValueError(
                f"Review verdict must be {mandatory.value} for this evidence"
            )
        return

    if proposed_state is EvidenceState.KEEP_TRUSTED:
        if not assessment.trusted_keep_eligible:
            raise ValueError("KEEP_TRUSTED evidence gate not satisfied")
        return

    if proposed_state is EvidenceState.KEEP_PROBATION:
        if not assessment.probation_keep_eligible:
            raise ValueError("KEEP_PROBATION evidence gate not satisfied")
        return

    if proposed_state in {
        EvidenceState.CUT_SIZE,
        EvidenceState.BENCH,
    }:
        raise ValueError(
            f"{proposed_state.value} trigger is not satisfied by this evidence"
        )

    # CANDIDATE / EVIDENCE_ACCUMULATING may remain conservative when there is
    # no mandatory demotion. Review is not forced to promote merely because a
    # minimum KEEP gate has become eligible.
