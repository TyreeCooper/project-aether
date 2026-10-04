"""Primary-source macro schedule verification for AETHER vNext.

This module deliberately separates aggregator discovery from primary-source
verification. It does not fetch network resources and it does not infer event
families from titles. Source adapters must supply canonical event_family values
from their own source-specific parsing rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


PRIMARY_MACRO_SOURCE_IDS = frozenset(
    {
        "bls",
        "federal_reserve",
        "bea",
    }
)


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class PrimaryMacroScheduleEvent:
    source_id: str
    source_event_id: str
    event_family: str
    scheduled_at_utc: datetime
    title: str
    source_url: str
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "source_event_id",
            "event_family",
            "title",
            "source_url",
        ):
            _canonical_text(name, getattr(self, name))
        if self.source_id not in PRIMARY_MACRO_SOURCE_IDS:
            raise ValueError("source_id must be an approved primary macro source")
        for name in ("scheduled_at_utc", "observed_at_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MacroVerificationRequest:
    event_id: str
    event_family: str
    scheduled_at_utc: datetime
    aggregator_source_id: str

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "event_family",
            "aggregator_source_id",
        ):
            _canonical_text(name, getattr(self, name))
        if self.scheduled_at_utc.tzinfo is None:
            raise ValueError("scheduled_at_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MacroVerificationResult:
    event_id: str
    event_family: str
    verified_official: bool
    verification_status: str
    primary_source_id: str | None
    primary_source_event_id: str | None
    primary_source_url: str | None
    official_scheduled_at_utc: datetime | None
    delta_seconds: float | None

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "event_family",
            "verification_status",
        ):
            _canonical_text(name, getattr(self, name))
        if not isinstance(self.verified_official, bool):
            raise ValueError("verified_official must be boolean")
        for name in (
            "primary_source_id",
            "primary_source_event_id",
            "primary_source_url",
        ):
            value = getattr(self, name)
            if value is not None:
                _canonical_text(name, value)
        if (
            self.official_scheduled_at_utc is not None
            and self.official_scheduled_at_utc.tzinfo is None
        ):
            raise ValueError("official_scheduled_at_utc must be timezone-aware")
        if self.delta_seconds is not None and self.delta_seconds < 0:
            raise ValueError("delta_seconds cannot be negative")
        if self.verified_official:
            if (
                self.primary_source_id is None
                or self.primary_source_event_id is None
                or self.primary_source_url is None
                or self.official_scheduled_at_utc is None
                or self.delta_seconds is None
            ):
                raise ValueError(
                    "verified macro result requires primary-source provenance"
                )


def verify_primary_macro_schedule(
    request: MacroVerificationRequest,
    official_events: Iterable[PrimaryMacroScheduleEvent],
    *,
    tolerance_seconds: int = 300,
) -> MacroVerificationResult:
    if (
        not isinstance(tolerance_seconds, int)
        or isinstance(tolerance_seconds, bool)
        or tolerance_seconds < 0
    ):
        raise ValueError("tolerance_seconds must be a nonnegative integer")

    matches: list[tuple[float, PrimaryMacroScheduleEvent]] = []
    for candidate in official_events:
        if candidate.event_family != request.event_family:
            continue
        delta = abs(
            (
                candidate.scheduled_at_utc - request.scheduled_at_utc
            ).total_seconds()
        )
        if delta <= tolerance_seconds:
            matches.append((delta, candidate))

    if not matches:
        return MacroVerificationResult(
            event_id=request.event_id,
            event_family=request.event_family,
            verified_official=False,
            verification_status="primary_schedule_mismatch",
            primary_source_id=None,
            primary_source_event_id=None,
            primary_source_url=None,
            official_scheduled_at_utc=None,
            delta_seconds=None,
        )

    delta, match = min(
        matches,
        key=lambda item: (
            item[0],
            item[1].source_id,
            item[1].source_event_id,
        ),
    )
    return MacroVerificationResult(
        event_id=request.event_id,
        event_family=request.event_family,
        verified_official=True,
        verification_status="matched_primary_schedule",
        primary_source_id=match.source_id,
        primary_source_event_id=match.source_event_id,
        primary_source_url=match.source_url,
        official_scheduled_at_utc=match.scheduled_at_utc,
        delta_seconds=delta,
    )
