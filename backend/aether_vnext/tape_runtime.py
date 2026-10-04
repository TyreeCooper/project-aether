"""Failure-isolated construction of official AETHER Tape consensus.

A source fault removes only that source from the current quorum. It never changes
execution-provider economics and never fabricates an observation to satisfy quorum.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from sqlalchemy.engine import Connection

from aether_vnext.store import VNextStore
from aether_vnext.tape import TapeCompositeObservation, TapeSourceObservation
from aether_vnext.tape_consensus import (
    TapeSourceRejection,
    build_tape_composite,
    decide_tape_consensus,
    qualify_tape_sources,
)
from aether_vnext.tape_policy import TapeQuorumPolicy


@dataclass(frozen=True, slots=True)
class TapeCycleResult:
    asset_id: str
    composite: TapeCompositeObservation
    source_failures: dict[str, str]
    qualification_rejections: tuple[TapeSourceRejection, ...]

    @property
    def source_count(self) -> int:
        return self.composite.source_count


def build_and_persist_tape_cycle(
    conn: Connection,
    store: VNextStore,
    *,
    asset_id: str,
    observations: Sequence[TapeSourceObservation],
    source_failures: Mapping[str, str],
    policy: TapeQuorumPolicy,
    as_of_utc: datetime,
    expected_contract_id: str | None = None,
) -> TapeCycleResult:
    """Persist observed sources and one reconciled composite for an asset cycle."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if not policy.operational:
        raise RuntimeError(
            "Tape policy is not operational: " + ",".join(policy.missing_requirements)
        )
    rows = tuple(observations)
    seen_sources = [row.source_id for row in rows]
    if len(seen_sources) != len(set(seen_sources)):
        raise ValueError("Tape cycle requires at most one observation per source")
    failure_ids = {str(key).strip() for key in source_failures if str(key).strip()}
    if failure_ids.intersection(seen_sources):
        raise ValueError("source cannot be both observed and failed in one Tape cycle")

    for row in rows:
        store.record_tape_source_observation(
            conn,
            row,
            recorded_at_utc=as_of_utc,
        )

    qualification = qualify_tape_sources(
        rows,
        asset_id=asset_id,
        policy=policy,
        as_of_utc=as_of_utc,
        expected_contract_id=expected_contract_id,
    )
    decision = decide_tape_consensus(
        qualification,
        policy=policy,
        as_of_utc=as_of_utc,
    )
    composite = build_tape_composite(
        decision,
        policy=policy,
        observed_at_utc=as_of_utc,
    )
    store.record_tape_composite(
        conn,
        composite,
        recorded_at_utc=as_of_utc,
    )
    return TapeCycleResult(
        asset_id=str(asset_id).strip().lower(),
        composite=composite,
        source_failures={
            str(key): str(value)
            for key, value in sorted(source_failures.items())
        },
        qualification_rejections=qualification.rejected,
    )
