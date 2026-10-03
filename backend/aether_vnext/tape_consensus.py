"""Normalization and qualification boundary for AETHER Consensus Tape feeds."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Sequence

from aether_vnext.tape import (
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)
from aether_vnext.tape_policy import TapeQuorumPolicy


@dataclass(frozen=True, slots=True)
class TapeSourceRejection:
    observation_id: str
    source_id: str
    reason: str
    age_ms: int | None


@dataclass(frozen=True, slots=True)
class TapeQualification:
    asset_id: str
    accepted: tuple[TapeSourceObservation, ...]
    rejected: tuple[TapeSourceRejection, ...]


def _age_ms(observation: TapeSourceObservation, *, as_of_utc: datetime) -> int:
    age = int((as_of_utc - observation.received_ts).total_seconds() * 1000)
    return age


def qualify_tape_sources(
    observations: Sequence[TapeSourceObservation],
    *,
    asset_id: str,
    policy: TapeQuorumPolicy,
    as_of_utc: datetime,
    expected_contract_id: str | None = None,
) -> TapeQualification:
    """Return independently qualified source observations without creating consensus.

    The latest observation per source wins. Stale/invalid rows remain rejected evidence
    and cannot enter the later consensus calculation.
    """
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    aid = str(asset_id).strip().lower()
    if not aid:
        raise ValueError("asset_id is required")
    if not policy.operational:
        raise RuntimeError(
            "Tape qualification policy is not operational: "
            + ",".join(policy.missing_requirements)
        )
    assert policy.max_source_age_ms is not None

    by_source: dict[str, TapeSourceObservation] = {}
    superseded: list[TapeSourceObservation] = []
    for observation in observations:
        if observation.asset_id != aid:
            raise ValueError("Tape source observation asset mismatch")
        prior = by_source.get(observation.source_id)
        if prior is None or (
            observation.received_ts,
            observation.observation_id,
        ) > (
            prior.received_ts,
            prior.observation_id,
        ):
            if prior is not None:
                superseded.append(prior)
            by_source[observation.source_id] = observation
        else:
            superseded.append(observation)

    accepted: list[TapeSourceObservation] = []
    rejected: list[TapeSourceRejection] = [
        TapeSourceRejection(
            observation_id=row.observation_id,
            source_id=row.source_id,
            reason="superseded_source_observation",
            age_ms=max(0, _age_ms(row, as_of_utc=as_of_utc)),
        )
        for row in superseded
    ]

    for source_id in sorted(by_source):
        observation = by_source[source_id]
        age = _age_ms(observation, as_of_utc=as_of_utc)
        reason: str | None = None
        if age < 0:
            reason = "source_received_after_decision_time"
        elif expected_contract_id is not None and (
            str(observation.contract_id or "").strip() != str(expected_contract_id).strip()
        ):
            reason = "contract_identity_mismatch"
        elif observation.quality is TapeSourceQuality.NOT_OBSERVED:
            reason = "source_not_observed"
        elif observation.quality is TapeSourceQuality.INVALID:
            reason = "source_invalid"
        elif observation.quality is TapeSourceQuality.STALE:
            reason = "source_stale"
        elif observation.mark is None:
            reason = "source_mark_missing"
        elif age > policy.max_source_age_ms:
            reason = "source_stale"
        elif observation.quality not in {
            TapeSourceQuality.HEALTHY,
            TapeSourceQuality.DEGRADED,
        }:
            reason = "source_unqualified"

        if reason is None:
            accepted.append(observation)
        else:
            rejected.append(
                TapeSourceRejection(
                    observation_id=observation.observation_id,
                    source_id=observation.source_id,
                    reason=reason,
                    age_ms=max(0, age),
                )
            )

    if len(accepted) > policy.max_sources:
        # Never silently exceed the reviewed five-source envelope. Keep the newest
        # five and preserve the rest as rejected evidence.
        accepted.sort(
            key=lambda row: (row.received_ts, row.source_id),
            reverse=True,
        )
        overflow = accepted[policy.max_sources:]
        accepted = accepted[:policy.max_sources]
        rejected.extend(
            TapeSourceRejection(
                observation_id=row.observation_id,
                source_id=row.source_id,
                reason="source_capacity_exceeded",
                age_ms=max(0, _age_ms(row, as_of_utc=as_of_utc)),
            )
            for row in overflow
        )

    accepted.sort(key=lambda row: row.source_id)
    rejected.sort(key=lambda row: (row.source_id, row.observation_id))
    return TapeQualification(
        asset_id=aid,
        accepted=tuple(accepted),
        rejected=tuple(rejected),
    )


@dataclass(frozen=True, slots=True)
class TapeConsensusDecision:
    asset_id: str
    state: TapeConsensusState
    median_mark: float | None
    inliers: tuple[TapeSourceObservation, ...]
    outliers: tuple[TapeSourceRejection, ...]
    qualification_rejections: tuple[TapeSourceRejection, ...]
    agreement_bps: float | None
    max_source_age_ms: int | None


def decide_tape_consensus(
    qualification: TapeQualification,
    *,
    policy: TapeQuorumPolicy,
    as_of_utc: datetime,
) -> TapeConsensusDecision:
    """Find a robust cross-source center and reject divergent observations.

    The median is the robust center. A source enters the inlier set only when its
    mark is within the reviewed divergence tolerance of that center. The final
    arithmetic composite is intentionally a later step.
    """
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if not policy.operational:
        raise RuntimeError("Tape consensus policy is not operational")
    assert policy.max_divergence_bps is not None

    qualified = tuple(qualification.accepted)
    if not qualified:
        return TapeConsensusDecision(
            asset_id=qualification.asset_id,
            state=TapeConsensusState.NOT_OBSERVED,
            median_mark=None,
            inliers=(),
            outliers=(),
            qualification_rejections=qualification.rejected,
            agreement_bps=None,
            max_source_age_ms=None,
        )

    marks = tuple(float(row.mark) for row in qualified if row.mark is not None)
    if len(marks) != len(qualified):
        raise RuntimeError("qualified Tape source unexpectedly lacks mark")
    center = float(median(marks))

    inliers: list[TapeSourceObservation] = []
    outliers: list[TapeSourceRejection] = []
    for row in qualified:
        assert row.mark is not None
        divergence_bps = abs(float(row.mark) - center) / center * 10_000.0
        if divergence_bps <= policy.max_divergence_bps:
            inliers.append(row)
        else:
            outliers.append(
                TapeSourceRejection(
                    observation_id=row.observation_id,
                    source_id=row.source_id,
                    reason="source_divergence_outlier",
                    age_ms=max(
                        0,
                        int(
                            (as_of_utc - row.received_ts).total_seconds()
                            * 1000
                        ),
                    ),
                )
            )

    if len(inliers) >= policy.required_quorum:
        state = TapeConsensusState.FULL
    elif len(qualified) >= policy.required_quorum:
        # There were enough fresh independent sources for full quorum, but they
        # failed to agree tightly enough. Never average disagreement away.
        state = TapeConsensusState.CONTESTED
    elif len(inliers) >= policy.degraded_quorum and not outliers:
        state = TapeConsensusState.DEGRADED
    elif len(qualified) >= policy.degraded_quorum:
        state = TapeConsensusState.CONTESTED
    elif len(inliers) == 1:
        state = TapeConsensusState.SINGLE_SOURCE
    else:
        state = TapeConsensusState.NOT_OBSERVED

    agreement_bps: float | None = None
    max_age: int | None = None
    if inliers:
        inlier_marks = [float(row.mark) for row in inliers if row.mark is not None]
        agreement_bps = (
            (max(inlier_marks) - min(inlier_marks)) / center * 10_000.0
            if center > 0
            else None
        )
        max_age = max(
            max(
                0,
                int((as_of_utc - row.received_ts).total_seconds() * 1000),
            )
            for row in inliers
        )

    return TapeConsensusDecision(
        asset_id=qualification.asset_id,
        state=state,
        median_mark=center,
        inliers=tuple(sorted(inliers, key=lambda row: row.source_id)),
        outliers=tuple(sorted(outliers, key=lambda row: row.source_id)),
        qualification_rejections=qualification.rejected,
        agreement_bps=agreement_bps,
        max_source_age_ms=max_age,
    )
