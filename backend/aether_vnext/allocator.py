"""F-005 deterministic FIRE sequencing allocator for AETHER vNext.

Allocator v1 is sequencing only. It receives already-eligible FIRE candidates and
returns allocation_order plus allocation_score_v1. It cannot write quantity, expand
risk, create signals, reserve capital, or mutate OPEN positions.

F-005 says conservative expectancy is a percentile rank inside the current eligible
batch but does not name a tie convention. This implementation uses an inclusive
average-rank percentile: minimum=0, maximum=100, equal ties share average rank, and a
single comparable candidate receives neutral 50 because there is no comparative
ranking. This controlled normalization is deterministic and does not change candidate
eligibility or risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Final, Iterable

from aether_vnext.freeze import (
    ALLOCATOR_VERSION,
    ALLOCATOR_WEIGHTS,
    EVIDENCE_QUALITY_SCORES,
    EvidenceState,
    GovernorState,
    OperationalState,
)


CORRELATION_HARD_BLOCK: Final = 0.75


@dataclass(frozen=True, slots=True)
class AllocationCandidate:
    ticket_id: str
    route_id: str
    trigger_bar_close_exchange_ts: datetime
    ros_norm: float
    conservative_net_expectancy_after_25_cost: float | None
    closed_trade_count: int
    evidence_state: EvidenceState
    operational_state: OperationalState
    governor_state: GovernorState
    runtime_eligible: bool
    has_open_same_cluster_exposure: bool
    mean_same_cluster_correlation: float | None
    execution_cost_ratio: float | None
    cluster_risk_utilization: float
    cost_headroom_component: float

    def __post_init__(self) -> None:
        if not self.ticket_id:
            raise ValueError("ticket_id is required")
        if not self.route_id:
            raise ValueError("route_id is required")
        if self.trigger_bar_close_exchange_ts.tzinfo is None:
            raise ValueError(
                "trigger_bar_close_exchange_ts must be timezone-aware"
            )
        for name, value in (
            ("ros_norm", self.ros_norm),
            ("cost_headroom_component", self.cost_headroom_component),
        ):
            numeric = float(value)
            if not math.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
                raise ValueError(f"{name} must be finite and in [0, 100]")
        if int(self.closed_trade_count) < 0:
            raise ValueError("closed_trade_count cannot be negative")
        if self.conservative_net_expectancy_after_25_cost is not None:
            if not math.isfinite(
                float(self.conservative_net_expectancy_after_25_cost)
            ):
                raise ValueError("conservative expectancy must be finite")
        if self.mean_same_cluster_correlation is not None:
            corr = float(self.mean_same_cluster_correlation)
            if not math.isfinite(corr) or not -1.0 <= corr <= 1.0:
                raise ValueError("mean_same_cluster_correlation must be in [-1,1]")
            if corr > CORRELATION_HARD_BLOCK:
                raise ValueError(
                    "candidate violates >0.75 same-cluster correlation hard block"
                )
        if self.execution_cost_ratio is not None:
            ratio = float(self.execution_cost_ratio)
            if not math.isfinite(ratio) or ratio < 0.0:
                raise ValueError("execution_cost_ratio must be finite and nonnegative")
        util = float(self.cluster_risk_utilization)
        if not math.isfinite(util) or not 0.0 <= util <= 1.0:
            raise ValueError("cluster_risk_utilization must be in [0,1]")

        # F-005 input contract is already-eligible FIRE only.
        if not self.runtime_eligible:
            raise ValueError("Allocator input must be runtime eligible")
        if self.evidence_state is EvidenceState.BENCH:
            raise ValueError("BENCH candidates are ineligible before scoring")
        if self.operational_state is not OperationalState.ENABLED:
            raise ValueError("DISABLED candidates are ineligible before scoring")
        if self.governor_state is not GovernorState.NORMAL:
            raise ValueError("HALT candidates are ineligible before scoring")


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    ticket_id: str
    route_id: str
    allocation_order: int
    allocation_score_v1: float
    ros_norm: float
    conservative_expectancy_score: float
    evidence_quality_score: float
    diversification_score: float
    execution_quality_score: float
    flags: tuple[str, ...]


def _comparable_expectancy(candidate: AllocationCandidate) -> float | None:
    value = candidate.conservative_net_expectancy_after_25_cost
    if int(candidate.closed_trade_count) < 15 or value is None:
        return None
    return float(value)


def _inclusive_average_rank_percentiles(
    candidates: tuple[AllocationCandidate, ...],
) -> dict[str, float]:
    """Percentile rank comparable expectancy with deterministic tie handling."""
    comparable = [
        (candidate.ticket_id, value)
        for candidate in candidates
        if (value := _comparable_expectancy(candidate)) is not None
    ]
    result = {
        candidate.ticket_id: 50.0
        for candidate in candidates
    }
    count = len(comparable)
    if count == 0:
        return result
    if count == 1:
        result[comparable[0][0]] = 50.0
        return result

    ordered_values = sorted(value for _, value in comparable)
    for ticket_id, value in comparable:
        positions = [
            index
            for index, ordered in enumerate(ordered_values)
            if ordered == value
        ]
        average_zero_based_rank = sum(positions) / len(positions)
        result[ticket_id] = (
            average_zero_based_rank / float(count - 1)
        ) * 100.0
    return result


def _diversification(
    candidate: AllocationCandidate,
) -> tuple[float, tuple[str, ...]]:
    if not candidate.has_open_same_cluster_exposure:
        return 100.0, ()
    corr = candidate.mean_same_cluster_correlation
    if corr is None:
        return 50.0, ("correlation_unknown",)
    numeric = float(corr)
    if numeric < 0.50:
        return 75.0, ()
    if numeric <= 0.75:
        return 50.0, ()
    # Constructor already refuses this, but keep the law local too.
    raise ValueError("same-cluster correlation hard block violated")


def _execution_quality(
    candidate: AllocationCandidate,
) -> tuple[float, tuple[str, ...]]:
    ratio = candidate.execution_cost_ratio
    if ratio is None:
        return 50.0, ("execution_quality_unknown",)
    value = float(ratio)
    if value <= 1.00:
        return 100.0, ()
    if value <= 1.10:
        return 80.0, ()
    if value <= 1.25:
        return 60.0, ()
    if value <= 1.50:
        return 30.0, ()
    return 0.0, ()


def allocate_fire_batch(
    candidates: Iterable[AllocationCandidate],
) -> tuple[AllocationDecision, ...]:
    rows = tuple(candidates)
    if not rows:
        return ()

    ticket_ids = [row.ticket_id for row in rows]
    route_ids = [row.route_id for row in rows]
    if len(ticket_ids) != len(set(ticket_ids)):
        raise ValueError("duplicate ticket_id in allocation batch")
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("duplicate route_id in allocation batch")

    expectancy_scores = _inclusive_average_rank_percentiles(rows)
    staged: list[tuple[AllocationCandidate, AllocationDecision]] = []

    for row in rows:
        evidence_score = float(
            EVIDENCE_QUALITY_SCORES[row.evidence_state.value]
        )
        diversification_score, diversification_flags = _diversification(row)
        execution_score, execution_flags = _execution_quality(row)
        expectancy_score = float(expectancy_scores[row.ticket_id])

        components = {
            "ros_norm": float(row.ros_norm),
            "conservative_expectancy_score": expectancy_score,
            "evidence_quality_score": evidence_score,
            "diversification_score": diversification_score,
            "execution_quality_score": execution_score,
        }
        score = sum(
            float(ALLOCATOR_WEIGHTS[name]) * value
            for name, value in components.items()
        )

        decision = AllocationDecision(
            ticket_id=row.ticket_id,
            route_id=row.route_id,
            allocation_order=0,
            allocation_score_v1=score,
            ros_norm=float(row.ros_norm),
            conservative_expectancy_score=expectancy_score,
            evidence_quality_score=evidence_score,
            diversification_score=diversification_score,
            execution_quality_score=execution_score,
            flags=tuple(
                sorted(
                    {
                        *diversification_flags,
                        *execution_flags,
                    }
                )
            ),
        )
        staged.append((row, decision))

    def sort_key(
        pair: tuple[AllocationCandidate, AllocationDecision],
    ) -> tuple[object, ...]:
        row, decision = pair
        expectancy = _comparable_expectancy(row)
        expectancy_key = (
            -float(expectancy)
            if expectancy is not None
            else math.inf
        )
        return (
            -decision.allocation_score_v1,
            expectancy_key,
            -float(row.ros_norm),
            float(row.cluster_risk_utilization),
            -float(row.cost_headroom_component),
            row.trigger_bar_close_exchange_ts,
            row.route_id,
        )

    ranked = sorted(staged, key=sort_key)
    return tuple(
        AllocationDecision(
            ticket_id=decision.ticket_id,
            route_id=decision.route_id,
            allocation_order=index,
            allocation_score_v1=decision.allocation_score_v1,
            ros_norm=decision.ros_norm,
            conservative_expectancy_score=(
                decision.conservative_expectancy_score
            ),
            evidence_quality_score=decision.evidence_quality_score,
            diversification_score=decision.diversification_score,
            execution_quality_score=decision.execution_quality_score,
            flags=decision.flags,
        )
        for index, (_, decision) in enumerate(ranked, start=1)
    )


def allocator_version() -> str:
    return ALLOCATOR_VERSION
