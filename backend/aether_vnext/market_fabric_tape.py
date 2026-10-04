"""MF-05 dual-domain AETHER Tape: executable truth plus witness evidence.

Witnesses can corroborate or challenge an authorized execution book. They can never
average into, replace, or overwrite executable bid/ask/depth.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Iterable


class ExecutionState(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    STALE = "STALE"
    NOT_OBSERVED = "NOT_OBSERVED"


class WitnessClass(StrEnum):
    IN_BAND = "IN_BAND"
    OUTSIDE_BAND = "OUTSIDE_BAND"
    PENDING = "PENDING"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    REJECTED = "REJECTED"


class EvidenceState(StrEnum):
    NOT_OBSERVED = "NOT_OBSERVED"
    CONTESTED = "CONTESTED"
    DIVERGED = "DIVERGED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    DEGRADED = "DEGRADED"
    FULL = "FULL"


@dataclass(frozen=True, slots=True)
class ExecutableTapeSnapshot:
    instrument_id: str
    route_id: str
    authorized_economic_source_id: str
    state: ExecutionState
    bid: float | None
    ask: float | None
    last_if_printed: float | None
    last_credible_age_ms: int | None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.route_id.strip():
            raise ValueError("instrument_id and route_id are required")
        if not self.authorized_economic_source_id.strip():
            raise ValueError("authorized_economic_source_id is required")
        if self.state is ExecutionState.EXECUTABLE:
            if self.bid is None or self.ask is None:
                raise ValueError("EXECUTABLE requires bid and ask")
            if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
                raise ValueError("invalid executable book")
        else:
            if self.bid is not None or self.ask is not None:
                raise ValueError("non-executable state must blank bid and ask")
        if self.last_credible_age_ms is not None and self.last_credible_age_ms < 0:
            raise ValueError("last_credible_age_ms cannot be negative")

    @property
    def mid(self) -> float | None:
        if self.state is not ExecutionState.EXECUTABLE:
            return None
        assert self.bid is not None and self.ask is not None
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class WitnessEvidencePolicy:
    required_effective_groups: int
    max_alignment_ms: int
    base_band_bps: float
    c_vol: float
    band_cap_bps: float
    persistence_evaluations: int
    hard_gap_multiple: float
    contested_ratio: float
    mutual_band_multiple: float
    basis_cap_bps: float

    def __post_init__(self) -> None:
        if self.required_effective_groups < 1:
            raise ValueError("required_effective_groups must be positive")
        if self.max_alignment_ms < 0:
            raise ValueError("max_alignment_ms cannot be negative")
        for name in (
            "base_band_bps",
            "c_vol",
            "band_cap_bps",
            "hard_gap_multiple",
            "mutual_band_multiple",
            "basis_cap_bps",
        ):
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.persistence_evaluations < 1:
            raise ValueError("persistence_evaluations must be positive")
        if not 0 < self.contested_ratio <= 1:
            raise ValueError("contested_ratio must be within (0, 1]")


@dataclass(frozen=True, slots=True)
class WitnessObservation:
    witness_id: str
    economic_source_id: str
    independence_group_id: str
    bid: float | None
    ask: float | None
    age_ms: int
    alignment_delta_ms: int
    spread_bps: float
    outside_band_evaluations: int = 0
    basis_adjustment_bps: float = 0.0
    available: bool = True
    structurally_valid: bool = True
    clock_trusted: bool = True

    def __post_init__(self) -> None:
        if not self.witness_id.strip():
            raise ValueError("witness_id is required")
        if not self.economic_source_id.strip() or not self.independence_group_id.strip():
            raise ValueError("economic source and independence group are required")
        if self.age_ms < 0 or self.alignment_delta_ms < 0:
            raise ValueError("age/alignment cannot be negative")
        if self.spread_bps < 0:
            raise ValueError("spread_bps cannot be negative")
        if self.bid is not None and (not isfinite(self.bid) or self.bid <= 0):
            raise ValueError("bid must be positive when present")
        if self.ask is not None and (not isfinite(self.ask) or self.ask <= 0):
            raise ValueError("ask must be positive when present")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("witness book crossed")

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class WitnessClassification:
    witness_id: str
    independence_group_id: str
    classification: WitnessClass
    reason: str
    gap_bps: float | None
    aligned_mid: float | None


@dataclass(frozen=True, slots=True)
class MarketIntelligenceSnapshot:
    instrument_id: str
    evidence_state: EvidenceState
    quorum_met: bool
    raw_witness_count: int
    effective_independent_count: int
    in_band_count: int
    outside_count: int
    pending_count: int
    max_gap_bps: float | None
    mutual_spread_bps: float | None
    classifications: tuple[WitnessClassification, ...]


@dataclass(frozen=True, slots=True)
class AetherTapeSnapshot:
    executable: ExecutableTapeSnapshot
    intelligence: MarketIntelligenceSnapshot


def _band_bps(
    *,
    policy: WitnessEvidencePolicy,
    realized_vol_bps: float,
    executable_spread_bps: float,
    witness_spread_bps: float,
) -> float:
    raw = max(
        policy.base_band_bps,
        policy.c_vol * max(realized_vol_bps, 0.0),
        0.5 * executable_spread_bps + 0.5 * witness_spread_bps,
    )
    return min(raw, policy.band_cap_bps)


def classify_witness(
    executable: ExecutableTapeSnapshot,
    witness: WitnessObservation,
    *,
    policy: WitnessEvidencePolicy,
    realized_vol_bps: float,
    max_witness_age_ms: int,
) -> WitnessClassification:
    if executable.state is not ExecutionState.EXECUTABLE or executable.mid is None:
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.UNAVAILABLE,
            "executable_reference_unavailable",
            None,
            None,
        )
    if not witness.available:
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.UNAVAILABLE,
            "witness_unavailable",
            None,
            None,
        )
    if not witness.structurally_valid or not witness.clock_trusted:
        reason = "structural_invalid" if not witness.structurally_valid else "clock_untrusted"
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.REJECTED,
            reason,
            None,
            None,
        )
    if witness.age_ms > max_witness_age_ms:
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.STALE,
            "witness_stale",
            None,
            None,
        )
    if witness.alignment_delta_ms > policy.max_alignment_ms:
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.REJECTED,
            "alignment_exceeded",
            None,
            None,
        )
    if abs(witness.basis_adjustment_bps) > policy.basis_cap_bps:
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.REJECTED,
            "basis_unqualified",
            None,
            None,
        )
    if witness.mid is None:
        return WitnessClassification(
            witness.witness_id,
            witness.independence_group_id,
            WitnessClass.REJECTED,
            "bbo_missing",
            None,
            None,
        )

    exec_mid = executable.mid
    assert exec_mid is not None
    aligned_mid = witness.mid * (1.0 + witness.basis_adjustment_bps / 10000.0)
    gap_bps = 10000.0 * (exec_mid - aligned_mid) / exec_mid
    executable_spread_bps = (
        10000.0 * ((executable.ask or 0.0) - (executable.bid or 0.0)) / exec_mid
    )
    band = _band_bps(
        policy=policy,
        realized_vol_bps=realized_vol_bps,
        executable_spread_bps=executable_spread_bps,
        witness_spread_bps=witness.spread_bps,
    )
    absolute_gap = abs(gap_bps)
    if absolute_gap <= band:
        klass = WitnessClass.IN_BAND
        reason = "inside_inclusive_band"
    elif absolute_gap >= policy.hard_gap_multiple * band:
        klass = WitnessClass.OUTSIDE_BAND
        reason = "hard_gap"
    elif witness.outside_band_evaluations >= policy.persistence_evaluations:
        klass = WitnessClass.OUTSIDE_BAND
        reason = "persistent_gap"
    else:
        klass = WitnessClass.PENDING
        reason = "gap_pending_persistence"
    return WitnessClassification(
        witness.witness_id,
        witness.independence_group_id,
        klass,
        reason,
        gap_bps,
        aligned_mid,
    )


def build_market_intelligence(
    executable: ExecutableTapeSnapshot,
    witnesses: Iterable[WitnessObservation],
    *,
    policy: WitnessEvidencePolicy,
    realized_vol_bps: float,
    max_witness_age_ms: int,
) -> MarketIntelligenceSnapshot:
    rows = tuple(witnesses)
    classified = tuple(
        classify_witness(
            executable,
            witness,
            policy=policy,
            realized_vol_bps=realized_vol_bps,
            max_witness_age_ms=max_witness_age_ms,
        )
        for witness in rows
    )

    eligible = tuple(
        row
        for row in classified
        if row.classification
        in {WitnessClass.IN_BAND, WitnessClass.OUTSIDE_BAND, WitnessClass.PENDING}
    )
    by_group: dict[str, list[WitnessClassification]] = {}
    for row in eligible:
        by_group.setdefault(row.independence_group_id, []).append(row)

    def group_class(items: list[WitnessClassification]) -> WitnessClass:
        classes = {item.classification for item in items}
        if WitnessClass.OUTSIDE_BAND in classes:
            return WitnessClass.OUTSIDE_BAND
        if WitnessClass.PENDING in classes:
            return WitnessClass.PENDING
        return WitnessClass.IN_BAND

    effective = {group: group_class(items) for group, items in by_group.items()}
    in_band = sum(value is WitnessClass.IN_BAND for value in effective.values())
    outside = sum(value is WitnessClass.OUTSIDE_BAND for value in effective.values())
    pending = sum(value is WitnessClass.PENDING for value in effective.values())
    effective_count = len(effective)
    quorum_met = effective_count >= policy.required_effective_groups

    fresh_mids = [
        row.aligned_mid
        for row in eligible
        if row.aligned_mid is not None
    ]
    mutual_spread_bps = None
    if len(fresh_mids) >= 2:
        low = min(fresh_mids)
        high = max(fresh_mids)
        center = (low + high) / 2.0
        mutual_spread_bps = 10000.0 * (high - low) / center if center > 0 else None

    max_gap = max(
        (abs(row.gap_bps) for row in eligible if row.gap_bps is not None),
        default=None,
    )

    if executable.state is not ExecutionState.EXECUTABLE or effective_count == 0:
        state = EvidenceState.NOT_OBSERVED
    else:
        contested_by_ratio = (
            effective_count > 0 and outside / effective_count >= policy.contested_ratio
        )
        exec_mid = executable.mid or 0.0
        exec_spread_bps = (
            0.0
            if exec_mid <= 0
            else 10000.0
            * ((executable.ask or 0.0) - (executable.bid or 0.0))
            / exec_mid
        )
        mutual_limit = policy.mutual_band_multiple * _band_bps(
            policy=policy,
            realized_vol_bps=realized_vol_bps,
            executable_spread_bps=exec_spread_bps,
            witness_spread_bps=0.0,
        )
        contested_by_mutual = (
            mutual_spread_bps is not None and mutual_spread_bps > mutual_limit
        )
        if contested_by_ratio or contested_by_mutual:
            state = EvidenceState.CONTESTED
        elif outside:
            state = EvidenceState.DIVERGED
        elif effective_count == 1:
            state = EvidenceState.SINGLE_SOURCE
        elif pending or not quorum_met or in_band < policy.required_effective_groups:
            state = EvidenceState.DEGRADED
        else:
            state = EvidenceState.FULL

    return MarketIntelligenceSnapshot(
        instrument_id=executable.instrument_id,
        evidence_state=state,
        quorum_met=quorum_met,
        raw_witness_count=len(rows),
        effective_independent_count=effective_count,
        in_band_count=in_band,
        outside_count=outside,
        pending_count=pending,
        max_gap_bps=max_gap,
        mutual_spread_bps=mutual_spread_bps,
        classifications=classified,
    )


def build_aether_tape_snapshot(
    executable: ExecutableTapeSnapshot,
    witnesses: Iterable[WitnessObservation],
    *,
    policy: WitnessEvidencePolicy,
    realized_vol_bps: float,
    max_witness_age_ms: int,
) -> AetherTapeSnapshot:
    intelligence = build_market_intelligence(
        executable,
        witnesses,
        policy=policy,
        realized_vol_bps=realized_vol_bps,
        max_witness_age_ms=max_witness_age_ms,
    )
    return AetherTapeSnapshot(executable=executable, intelligence=intelligence)
