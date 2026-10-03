"""Research-only event reaction materialization for AETHER vNext.

The roadmap requires dedicated reaction rollups at 5m, 15m, 30m, 1h, 4h,
and 24h. This module does not select market bars or infer price tolerances.
Callers provide already-observed reaction measurements with immutable
provenance; this layer validates and materializes them deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


EVENT_REACTION_HORIZONS: tuple[tuple[str, int], ...] = (
    ("5m", 5 * 60),
    ("15m", 15 * 60),
    ("30m", 30 * 60),
    ("1h", 60 * 60),
    ("4h", 4 * 60 * 60),
    ("24h", 24 * 60 * 60),
)
_HORIZON_BY_SECONDS = {
    seconds: label for label, seconds in EVENT_REACTION_HORIZONS
}


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class EventReactionMeasurement:
    event_id: str
    asset_id: str
    event_at_utc: datetime
    information_available_at_utc: datetime
    horizon_seconds: int
    observed_at_utc: datetime
    return_value: float
    observation_id: str
    market_data_version: str
    research_only: bool = True

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "asset_id",
            "observation_id",
            "market_data_version",
        ):
            _canonical_text(name, getattr(self, name))
        for name in (
            "event_at_utc",
            "information_available_at_utc",
            "observed_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (
            not isinstance(self.horizon_seconds, int)
            or isinstance(self.horizon_seconds, bool)
            or self.horizon_seconds not in _HORIZON_BY_SECONDS
        ):
            raise ValueError(
                "horizon_seconds must be a canonical event-reaction horizon"
            )
        if isinstance(self.return_value, bool) or not math.isfinite(
            float(self.return_value)
        ):
            raise ValueError("return_value must be finite numeric")
        if self.observed_at_utc < self.information_available_at_utc:
            raise ValueError(
                "reaction observation cannot precede information availability"
            )
        target_utc = self.event_at_utc.timestamp() + self.horizon_seconds
        if self.observed_at_utc.timestamp() < target_utc:
            raise ValueError(
                "reaction observation cannot precede its horizon target"
            )
        if self.research_only is not True:
            raise ValueError("event reaction measurement is research_only")

    @property
    def horizon_label(self) -> str:
        return _HORIZON_BY_SECONDS[self.horizon_seconds]


@dataclass(frozen=True, slots=True)
class EventReactionRollup:
    event_id: str
    asset_id: str
    event_at_utc: datetime
    information_available_at_utc: datetime
    market_data_version: str
    measurements: tuple[EventReactionMeasurement, ...]
    materialized_at_utc: datetime
    research_only: bool = True

    def __post_init__(self) -> None:
        for name in ("event_id", "asset_id", "market_data_version"):
            _canonical_text(name, getattr(self, name))
        for name in (
            "event_at_utc",
            "information_available_at_utc",
            "materialized_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not isinstance(self.measurements, tuple) or not self.measurements:
            raise ValueError("measurements must be a nonempty immutable tuple")
        seen: set[int] = set()
        for row in self.measurements:
            if row.event_id != self.event_id:
                raise ValueError("reaction measurement event_id mismatch")
            if row.asset_id != self.asset_id:
                raise ValueError("reaction measurement asset_id mismatch")
            if row.event_at_utc != self.event_at_utc:
                raise ValueError("reaction measurement event time mismatch")
            if (
                row.information_available_at_utc
                != self.information_available_at_utc
            ):
                raise ValueError(
                    "reaction measurement information availability mismatch"
                )
            if row.market_data_version != self.market_data_version:
                raise ValueError("reaction measurement market-data mismatch")
            if row.horizon_seconds in seen:
                raise ValueError("duplicate event-reaction horizon")
            seen.add(row.horizon_seconds)
            if row.observed_at_utc > self.materialized_at_utc:
                raise ValueError(
                    "materialization cannot precede reaction observation"
                )
        if self.research_only is not True:
            raise ValueError("event reaction rollup is research_only")

    @property
    def complete(self) -> bool:
        return {
            row.horizon_seconds for row in self.measurements
        } == set(_HORIZON_BY_SECONDS)

    def returns_by_horizon(self) -> dict[str, float]:
        return {
            row.horizon_label: float(row.return_value)
            for row in sorted(
                self.measurements,
                key=lambda item: item.horizon_seconds,
            )
        }


def materialize_event_reaction_rollup(
    measurements: tuple[EventReactionMeasurement, ...],
    *,
    materialized_at_utc: datetime,
) -> EventReactionRollup:
    if not isinstance(measurements, tuple) or not measurements:
        raise ValueError("measurements must be a nonempty immutable tuple")
    first = measurements[0]
    return EventReactionRollup(
        event_id=first.event_id,
        asset_id=first.asset_id,
        event_at_utc=first.event_at_utc,
        information_available_at_utc=first.information_available_at_utc,
        market_data_version=first.market_data_version,
        measurements=measurements,
        materialized_at_utc=materialized_at_utc,
        research_only=True,
    )
