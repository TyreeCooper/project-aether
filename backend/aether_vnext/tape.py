"""Canonical contracts for the independent AETHER Consensus Tape.

The Tape is market-data infrastructure. It can establish observed market truth for
strategy and risk context, but it cannot submit orders, alter provider economics, or
grant execution authority. Execution providers remain separate runtime bindings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
from typing import Final


MAX_TAPE_SOURCES: Final = 5


class TapeSourceQuality(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_OBSERVED = "NOT_OBSERVED"


class TapeConsensusState(StrEnum):
    FULL = "FULL"
    DEGRADED = "DEGRADED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    CONTESTED = "CONTESTED"
    NOT_OBSERVED = "NOT_OBSERVED"


class TapeConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CONTESTED = "CONTESTED"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class TapeSourceObservation:
    observation_id: str
    asset_id: str
    source_id: str
    venue: str
    source_symbol: str
    contract_id: str | None
    bid: float | None
    ask: float | None
    last: float | None
    mark: float | None
    exchange_ts: datetime | None
    received_ts: datetime
    age_ms: int
    quality: TapeSourceQuality
    source_data_version: str
    source_ref: str

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "asset_id",
            "source_id",
            "venue",
            "source_symbol",
            "source_data_version",
            "source_ref",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.asset_id != self.asset_id.strip().lower():
            raise ValueError("asset_id must be canonical lowercase")
        if self.received_ts.tzinfo is None:
            raise ValueError("received_ts must be timezone-aware")
        if self.exchange_ts is not None and self.exchange_ts.tzinfo is None:
            raise ValueError("exchange_ts must be timezone-aware when present")
        if isinstance(self.age_ms, bool) or self.age_ms < 0:
            raise ValueError("age_ms must be a nonnegative integer")
        for name in ("bid", "ask", "last", "mark"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"{name} must be finite and positive when present")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")

    @property
    def can_authorize_execution(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class TapeCompositeObservation:
    composite_id: str
    asset_id: str
    observed_at_utc: datetime
    state: TapeConsensusState
    composite_mark: float | None
    median_mark: float | None
    accepted_source_ids: tuple[str, ...]
    rejected_source_ids: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    source_count: int
    quorum_required: int
    max_source_age_ms: int | None
    agreement_bps: float | None
    provenance_complete: bool

    def __post_init__(self) -> None:
        if not self.composite_id.strip():
            raise ValueError("composite_id is required")
        if self.asset_id != self.asset_id.strip().lower() or not self.asset_id:
            raise ValueError("asset_id must be canonical lowercase")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if self.quorum_required < 1 or self.quorum_required > MAX_TAPE_SOURCES:
            raise ValueError("quorum_required must be between 1 and 5")
        if self.source_count != len(self.accepted_source_ids):
            raise ValueError("source_count must equal accepted source count")
        if len(set(self.source_observation_ids)) != len(self.source_observation_ids):
            raise ValueError("source observation lineage must be unique")
        if self.composite_mark is not None and (
            not math.isfinite(float(self.composite_mark))
            or float(self.composite_mark) <= 0
        ):
            raise ValueError("composite_mark must be finite and positive")
        if self.median_mark is not None and (
            not math.isfinite(float(self.median_mark))
            or float(self.median_mark) <= 0
        ):
            raise ValueError("median_mark must be finite and positive")
        if self.max_source_age_ms is not None and self.max_source_age_ms < 0:
            raise ValueError("max_source_age_ms cannot be negative")
        if self.agreement_bps is not None and self.agreement_bps < 0:
            raise ValueError("agreement_bps cannot be negative")
        if self.state is TapeConsensusState.NOT_OBSERVED:
            if self.composite_mark is not None or self.source_count:
                raise ValueError("NOT_OBSERVED cannot publish a composite mark")
        if self.state is TapeConsensusState.CONTESTED and self.composite_mark is not None:
            raise ValueError("CONTESTED cannot publish an executable composite mark")
        if self.source_count > MAX_TAPE_SOURCES:
            raise ValueError("Tape supports at most five accepted sources")

    @property
    def confidence(self) -> TapeConfidence:
        return {
            TapeConsensusState.FULL: TapeConfidence.HIGH,
            TapeConsensusState.DEGRADED: TapeConfidence.MEDIUM,
            TapeConsensusState.SINGLE_SOURCE: TapeConfidence.LOW,
            TapeConsensusState.CONTESTED: TapeConfidence.CONTESTED,
            TapeConsensusState.NOT_OBSERVED: TapeConfidence.NONE,
        }[self.state]

    @property
    def can_authorize_execution(self) -> bool:
        return False
