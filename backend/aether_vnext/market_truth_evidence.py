"""Layer 4C: independent witness evidence axis.

Witnesses are evidence only. This module cannot create or mutate executable bid/ask.
All calculations produced here are explicitly NON_EXECUTABLE.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable

from aether_vnext.market_truth_contract import EvidenceState, ExecutionState
from aether_vnext.market_truth_fabric import ExecutableBookSnapshot
from aether_vnext.market_truth_provider import ProviderCardRegistry
from aether_vnext.market_truth_route import RouteRecord


UTC = timezone.utc
NON_EXECUTABLE_AUTHORITY = "NON_EXECUTABLE"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("witness timestamps must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WitnessObservation:
    canonical_instrument_id: str
    provider_id: str
    venue: str
    bid: float | None
    ask: float | None
    last_if_printed: float | None
    venue_time_utc: datetime | None
    receive_time_utc: datetime

    def __post_init__(self) -> None:
        for name in ("canonical_instrument_id", "provider_id", "venue"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        for name in ("bid", "ask", "last_if_printed"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be positive and finite when present")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("witness book is crossed")
        if self.venue_time_utc is not None:
            _utc(self.venue_time_utc)
        _utc(self.receive_time_utc)

    @property
    def coherent_two_sided_book(self) -> bool:
        return self.bid is not None and self.ask is not None and self.bid <= self.ask


@dataclass(frozen=True, slots=True)
class WitnessAssessment:
    provider_id: str
    fresh: bool
    coherent: bool
    gap_bps_to_executable: float | None
    authority: str = NON_EXECUTABLE_AUTHORITY


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    canonical_instrument_id: str
    route_id: str
    state: EvidenceState
    configured_witness_count: int
    observed_witness_count: int
    fresh_coherent_witness_count: int
    assessments: tuple[WitnessAssessment, ...]
    max_gap_bps_to_executable: float | None
    authority: str = NON_EXECUTABLE_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != NON_EXECUTABLE_AUTHORITY:
            raise ValueError("witness evidence must be NON_EXECUTABLE")


def _book_gap_bps(
    executable: ExecutableBookSnapshot,
    witness: WitnessObservation,
) -> float | None:
    """Compare corresponding provider fields directly; never average prices."""
    if executable.state is not ExecutionState.EXECUTABLE:
        return None
    if executable.bid is None or executable.ask is None:
        return None
    if witness.bid is None or witness.ask is None:
        return None
    bid_gap = abs(witness.bid - executable.bid) / executable.bid * 10_000.0
    ask_gap = abs(witness.ask - executable.ask) / executable.ask * 10_000.0
    return max(bid_gap, ask_gap)


def _pairwise_contested(
    rows: tuple[WitnessObservation, ...],
    *,
    divergence_bps: float,
) -> bool:
    for i, left in enumerate(rows):
        if not left.coherent_two_sided_book:
            continue
        for right in rows[i + 1:]:
            if not right.coherent_two_sided_book:
                continue
            assert left.bid is not None and left.ask is not None
            assert right.bid is not None and right.ask is not None
            bid_gap = abs(left.bid - right.bid) / min(left.bid, right.bid) * 10_000.0
            ask_gap = abs(left.ask - right.ask) / min(left.ask, right.ask) * 10_000.0
            if max(bid_gap, ask_gap) > divergence_bps:
                return True
    return False


def build_evidence_snapshot(
    route: RouteRecord,
    executable: ExecutableBookSnapshot,
    witnesses: Iterable[WitnessObservation],
    *,
    providers: ProviderCardRegistry,
    as_of_utc: datetime,
    max_witness_age_ms: int,
    divergence_bps: float,
) -> EvidenceSnapshot:
    if max_witness_age_ms <= 0:
        raise ValueError("max_witness_age_ms must be positive")
    if divergence_bps <= 0:
        raise ValueError("divergence_bps must be positive")
    now = _utc(as_of_utc)
    configured = tuple(str(x).strip().lower() for x in route.witness_provider_ids)
    if not configured:
        return EvidenceSnapshot(
            canonical_instrument_id=route.canonical_instrument_id,
            route_id=route.route_id,
            state=EvidenceState.NO_WITNESS,
            configured_witness_count=0,
            observed_witness_count=0,
            fresh_coherent_witness_count=0,
            assessments=(),
            max_gap_bps_to_executable=None,
        )

    by_provider: dict[str, WitnessObservation] = {}
    for row in witnesses:
        if row.canonical_instrument_id.strip().lower() != route.canonical_instrument_id.strip().lower():
            raise ValueError("witness instrument does not match Route")
        provider_id = row.provider_id.strip().lower()
        if provider_id not in configured:
            raise ValueError(f"provider is not a configured Route witness: {provider_id}")
        if provider_id == route.executable_provider_id.strip().lower():
            raise ValueError("executable provider cannot enter witness lane")
        card = providers.require(provider_id)
        if not card.can_observe:
            raise ValueError(f"witness provider lacks observe capability: {provider_id}")
        if card.venue.strip().lower() != row.venue.strip().lower():
            raise ValueError("witness venue does not match Provider Card")
        prior = by_provider.get(provider_id)
        if prior is None or _utc(row.receive_time_utc) >= _utc(prior.receive_time_utc):
            by_provider[provider_id] = row

    assessments: list[WitnessAssessment] = []
    fresh_rows: list[WitnessObservation] = []
    gaps: list[float] = []
    for provider_id in configured:
        row = by_provider.get(provider_id)
        if row is None:
            continue
        age_ms = max(0, int((now - _utc(row.receive_time_utc)).total_seconds() * 1000))
        fresh = age_ms <= max_witness_age_ms
        coherent = row.coherent_two_sided_book
        gap = _book_gap_bps(executable, row) if fresh and coherent else None
        assessments.append(WitnessAssessment(
            provider_id=provider_id,
            fresh=fresh,
            coherent=coherent,
            gap_bps_to_executable=gap,
        ))
        if fresh and coherent:
            fresh_rows.append(row)
            if gap is not None:
                gaps.append(gap)

    if not fresh_rows:
        state = EvidenceState.NO_WITNESS
    elif any(gap > divergence_bps for gap in gaps):
        state = EvidenceState.DIVERGED
    elif _pairwise_contested(tuple(fresh_rows), divergence_bps=divergence_bps):
        state = EvidenceState.CONTESTED
    elif len(fresh_rows) == 1:
        state = EvidenceState.SINGLE_SOURCE
    elif len(fresh_rows) < len(configured):
        state = EvidenceState.DEGRADED
    else:
        state = EvidenceState.FULL

    return EvidenceSnapshot(
        canonical_instrument_id=route.canonical_instrument_id,
        route_id=route.route_id,
        state=state,
        configured_witness_count=len(configured),
        observed_witness_count=len(by_provider),
        fresh_coherent_witness_count=len(fresh_rows),
        assessments=tuple(assessments),
        max_gap_bps_to_executable=max(gaps) if gaps else None,
    )


def corroborated_badge(
    executable: ExecutableBookSnapshot,
    evidence: EvidenceSnapshot,
) -> bool:
    """Presentation paint only; consumers must read the two canonical states."""
    return (
        executable.state is ExecutionState.EXECUTABLE
        and evidence.state in {EvidenceState.FULL, EvidenceState.DEGRADED}
    )
