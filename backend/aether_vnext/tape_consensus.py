"""Normalization and qualification boundary for AETHER Consensus Tape feeds."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from aether_vnext.tape import TapeSourceObservation, TapeSourceQuality
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
