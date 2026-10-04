"""AETHER vNext edge-decay monitor.

P8 requires rolling-vs-reference evidence and automatic Review queueing, but it does
not bind numeric rolling-window sizes or a universal "materially worsens" threshold.
This module therefore computes exact directional deltas and queues Review when decay
is source-bound by an approved materiality decision, or when deterioration exists but
materiality remains unbound. It never mutates strategy, Risk, or Review state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
from typing import Mapping


class DecayStatus(StrEnum):
    NO_DECAY_SIGNAL = "NO_DECAY_SIGNAL"
    NO_MATERIAL_DECAY = "NO_MATERIAL_DECAY"
    MATERIALITY_UNBOUND = "MATERIALITY_UNBOUND"
    DECAY_CONFIRMED = "DECAY_CONFIRMED"


@dataclass(frozen=True, slots=True)
class DecayCohort:
    evidence_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    configuration_hash: str
    as_of_utc: datetime
    n: int
    net_expectancy_usd: float
    capture_efficiency: float
    execution_drag_usd_per_trade: float
    average_cost_usd_per_trade: float
    regime_mix: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "route_id",
            "playbook_id",
            "playbook_version",
            "configuration_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if int(self.n) <= 0:
            raise ValueError("n must be positive")
        for name in (
            "net_expectancy_usd",
            "capture_efficiency",
            "execution_drag_usd_per_trade",
            "average_cost_usd_per_trade",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if float(self.execution_drag_usd_per_trade) < 0.0:
            raise ValueError("execution_drag_usd_per_trade cannot be negative")
        if float(self.average_cost_usd_per_trade) < 0.0:
            raise ValueError("average_cost_usd_per_trade cannot be negative")
        if not self.regime_mix:
            raise ValueError("regime_mix is required")
        total = 0.0
        for label, share in self.regime_mix.items():
            if not str(label).strip():
                raise ValueError("regime_mix labels cannot be blank")
            numeric = float(share)
            if not math.isfinite(numeric) or numeric < 0.0:
                raise ValueError("regime_mix shares must be finite and nonnegative")
            total += numeric
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("regime_mix shares must sum to 1")


@dataclass(frozen=True, slots=True)
class DecayAssessment:
    request_review: bool
    status: DecayStatus
    reference_evidence_id: str
    recent_evidence_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    configuration_hash: str
    expectancy_delta_usd: float
    capture_efficiency_delta: float
    execution_drag_delta_usd_per_trade: float
    average_cost_delta_usd_per_trade: float
    regime_mix_delta: dict[str, float]
    deterioration_dimensions: tuple[str, ...]
    materiality_decision: bool | None
    materiality_policy_version: str | None
    unresolved_rules: tuple[str, ...]


def assess_decay(
    reference: DecayCohort,
    recent: DecayCohort,
    *,
    materiality_decision: bool | None,
    materiality_policy_version: str | None,
) -> DecayAssessment:
    family_fields = (
        "route_id",
        "playbook_id",
        "playbook_version",
        "configuration_hash",
    )
    mismatch = [
        name
        for name in family_fields
        if getattr(reference, name) != getattr(recent, name)
    ]
    if mismatch:
        raise ValueError(
            "reference/recent decay cohorts cannot cross evidence family: "
            + ",".join(mismatch)
        )
    if recent.as_of_utc <= reference.as_of_utc:
        raise ValueError("recent cohort must be later than reference cohort")
    if materiality_decision is not None and not str(
        materiality_policy_version or ""
    ).strip():
        raise ValueError(
            "materiality_policy_version is required for a bound decision"
        )

    expectancy_delta = (
        float(recent.net_expectancy_usd)
        - float(reference.net_expectancy_usd)
    )
    capture_delta = (
        float(recent.capture_efficiency)
        - float(reference.capture_efficiency)
    )
    execution_drag_delta = (
        float(recent.execution_drag_usd_per_trade)
        - float(reference.execution_drag_usd_per_trade)
    )
    cost_delta = (
        float(recent.average_cost_usd_per_trade)
        - float(reference.average_cost_usd_per_trade)
    )

    regime_labels = sorted(
        set(reference.regime_mix) | set(recent.regime_mix)
    )
    regime_delta = {
        label: (
            float(recent.regime_mix.get(label, 0.0))
            - float(reference.regime_mix.get(label, 0.0))
        )
        for label in regime_labels
    }

    deterioration: list[str] = []
    if expectancy_delta < 0.0:
        deterioration.append("net_expectancy")
    if capture_delta < 0.0:
        deterioration.append("capture_efficiency")
    if execution_drag_delta > 0.0:
        deterioration.append("execution_drag")
    if cost_delta > 0.0:
        deterioration.append("cost_drift")
    if any(abs(delta) > 1e-12 for delta in regime_delta.values()):
        deterioration.append("regime_mix_change")

    unresolved: list[str] = []
    if materiality_decision is True:
        status = DecayStatus.DECAY_CONFIRMED
        request_review = True
    elif materiality_decision is False:
        status = DecayStatus.NO_MATERIAL_DECAY
        request_review = False
    elif deterioration:
        status = DecayStatus.MATERIALITY_UNBOUND
        request_review = True
        unresolved.extend(
            (
                "material_deterioration_threshold_unbound",
                "rolling_reference_window_size_unbound",
            )
        )
    else:
        status = DecayStatus.NO_DECAY_SIGNAL
        request_review = False

    return DecayAssessment(
        request_review=request_review,
        status=status,
        reference_evidence_id=reference.evidence_id,
        recent_evidence_id=recent.evidence_id,
        route_id=recent.route_id,
        playbook_id=recent.playbook_id,
        playbook_version=recent.playbook_version,
        configuration_hash=recent.configuration_hash,
        expectancy_delta_usd=expectancy_delta,
        capture_efficiency_delta=capture_delta,
        execution_drag_delta_usd_per_trade=execution_drag_delta,
        average_cost_delta_usd_per_trade=cost_delta,
        regime_mix_delta=regime_delta,
        deterioration_dimensions=tuple(deterioration),
        materiality_decision=materiality_decision,
        materiality_policy_version=(
            str(materiality_policy_version)
            if materiality_policy_version is not None
            else None
        ),
        unresolved_rules=tuple(unresolved),
    )
