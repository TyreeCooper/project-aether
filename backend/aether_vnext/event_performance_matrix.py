"""Descriptive mechanism-vs-event performance matrix for AETHER vNext.

This module summarizes explicitly linked observations. It does not infer event
causation, does not award strategy evidence, and cannot authorize trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable


EVENT_REGIME_PHASES = frozenset({"pre_event", "during_event", "post_event"})


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _canonical_tuple(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an immutable tuple")
    for value in values:
        _canonical_text(f"{name} entry", value)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class MechanismEventPerformanceObservation:
    observation_id: str
    event_id: str
    event_type: str
    mechanism_id: str
    playbook_id: str
    playbook_version: str
    route_id: str
    asset_id: str
    regime_phase: str
    regime_id: str
    net_pnl_usd: float
    observed_at_utc: datetime
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "event_id",
            "event_type",
            "mechanism_id",
            "playbook_id",
            "playbook_version",
            "route_id",
            "asset_id",
            "regime_id",
        ):
            _canonical_text(name, getattr(self, name))
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.regime_phase not in EVENT_REGIME_PHASES:
            raise ValueError("invalid event regime phase")
        if isinstance(self.net_pnl_usd, bool) or not math.isfinite(
            float(self.net_pnl_usd)
        ):
            raise ValueError("net_pnl_usd must be finite numeric")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        _canonical_tuple("source_record_ids", self.source_record_ids)


@dataclass(frozen=True, slots=True, order=True)
class MechanismEventPerformanceKey:
    event_type: str
    mechanism_id: str
    playbook_id: str
    playbook_version: str
    route_id: str
    asset_id: str
    regime_phase: str
    regime_id: str


@dataclass(frozen=True, slots=True)
class MechanismEventPerformanceCell:
    key: MechanismEventPerformanceKey
    sample_count: int
    win_count: int
    loss_count: int
    flat_count: int
    net_pnl_usd: float
    mean_net_pnl_usd: float
    observation_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    association_only: bool = True
    causal_claim: bool = False
    trade_influence_allowed: bool = False
    independent_evidence_credit: bool = False

    def __post_init__(self) -> None:
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if self.win_count + self.loss_count + self.flat_count != self.sample_count:
            raise ValueError("outcome counts must reconcile to sample_count")
        if len(self.observation_ids) != self.sample_count:
            raise ValueError("observation_ids must align with sample_count")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("observation_ids cannot contain duplicates")
        if self.association_only is not True or self.causal_claim is not False:
            raise ValueError("event performance matrix cannot claim causation")
        if self.trade_influence_allowed is not False:
            raise ValueError("event performance matrix cannot influence trades")
        if self.independent_evidence_credit is not False:
            raise ValueError(
                "event performance matrix cannot receive independent evidence credit"
            )
        if not math.isclose(
            self.mean_net_pnl_usd * self.sample_count,
            self.net_pnl_usd,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("mean_net_pnl_usd must reconcile to net_pnl_usd")


def _key(
    row: MechanismEventPerformanceObservation,
) -> MechanismEventPerformanceKey:
    return MechanismEventPerformanceKey(
        event_type=row.event_type,
        mechanism_id=row.mechanism_id,
        playbook_id=row.playbook_id,
        playbook_version=row.playbook_version,
        route_id=row.route_id,
        asset_id=row.asset_id,
        regime_phase=row.regime_phase,
        regime_id=row.regime_id,
    )


def build_mechanism_event_performance_matrix(
    observations: Iterable[MechanismEventPerformanceObservation],
) -> tuple[MechanismEventPerformanceCell, ...]:
    """Aggregate declared event/trade links without inferring causal relationships."""
    grouped: dict[
        MechanismEventPerformanceKey,
        list[MechanismEventPerformanceObservation],
    ] = {}
    seen: set[str] = set()

    for row in observations:
        if row.observation_id in seen:
            raise ValueError("duplicate event-performance observation_id")
        seen.add(row.observation_id)
        grouped.setdefault(_key(row), []).append(row)

    cells: list[MechanismEventPerformanceCell] = []
    for key in sorted(grouped):
        rows = sorted(
            grouped[key],
            key=lambda row: (row.observed_at_utc, row.observation_id),
        )
        net = math.fsum(row.net_pnl_usd for row in rows)
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for row in rows
                    for source_id in row.source_record_ids
                }
            )
        )
        cells.append(
            MechanismEventPerformanceCell(
                key=key,
                sample_count=len(rows),
                win_count=sum(row.net_pnl_usd > 0 for row in rows),
                loss_count=sum(row.net_pnl_usd < 0 for row in rows),
                flat_count=sum(row.net_pnl_usd == 0 for row in rows),
                net_pnl_usd=net,
                mean_net_pnl_usd=net / len(rows),
                observation_ids=tuple(row.observation_id for row in rows),
                source_record_ids=source_ids,
            )
        )

    return tuple(cells)
