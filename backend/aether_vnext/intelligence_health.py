"""Intelligence source freshness and cross-source conflict controls.

Thresholds are supplied by the owning source/feed configuration. This module
does not invent universal freshness policy and never converts degraded,
missing, or conflicting intelligence into neutral.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


HEALTH_STATES = frozenset(
    {
        "healthy",
        "partial",
        "stale",
        "degraded",
        "unavailable",
        "unconfigured",
    }
)
CONFLICT_STATES = frozenset(
    {"insufficient", "aligned", "conflict"}
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
class SourceHealthInput:
    source_id: str
    configured: bool
    observed_at_utc: datetime
    last_success_at_utc: datetime | None
    stale_after_seconds: int
    degraded: bool = False
    coverage_complete: bool = True
    last_error: str | None = None

    def __post_init__(self) -> None:
        _canonical_text("source_id", self.source_id)
        if not isinstance(self.configured, bool):
            raise ValueError("configured must be boolean")
        if not isinstance(self.degraded, bool):
            raise ValueError("degraded must be boolean")
        if not isinstance(self.coverage_complete, bool):
            raise ValueError("coverage_complete must be boolean")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if (
            self.last_success_at_utc is not None
            and self.last_success_at_utc.tzinfo is None
        ):
            raise ValueError(
                "last_success_at_utc must be timezone-aware when present"
            )
        if (
            not isinstance(self.stale_after_seconds, int)
            or isinstance(self.stale_after_seconds, bool)
            or self.stale_after_seconds <= 0
        ):
            raise ValueError(
                "stale_after_seconds must be a positive integer"
            )
        if self.last_error is not None:
            _canonical_text("last_error", self.last_error)
        if (
            self.last_success_at_utc is not None
            and self.last_success_at_utc > self.observed_at_utc
        ):
            raise ValueError(
                "last_success_at_utc cannot follow observed_at_utc"
            )


@dataclass(frozen=True, slots=True)
class SourceHealthSnapshot:
    source_id: str
    state: str
    observed_at_utc: datetime
    last_success_at_utc: datetime | None
    age_seconds: float | None
    stale_after_seconds: int
    last_error: str | None
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        _canonical_text("source_id", self.source_id)
        if self.state not in HEALTH_STATES:
            raise ValueError("invalid health state")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if self.age_seconds is not None and self.age_seconds < 0:
            raise ValueError("age_seconds cannot be negative")
        if self.trade_influence_enabled is not False:
            raise ValueError(
                "intelligence health cannot enable trade influence"
            )


def derive_source_health(
    health: SourceHealthInput,
) -> SourceHealthSnapshot:
    age_seconds = (
        None
        if health.last_success_at_utc is None
        else (
            health.observed_at_utc - health.last_success_at_utc
        ).total_seconds()
    )
    if not health.configured:
        state = "unconfigured"
    elif health.degraded:
        state = "degraded"
    elif health.last_success_at_utc is None:
        state = "unavailable"
    elif (
        age_seconds is not None
        and age_seconds > health.stale_after_seconds
    ):
        state = "stale"
    elif not health.coverage_complete:
        state = "partial"
    else:
        state = "healthy"
    return SourceHealthSnapshot(
        source_id=health.source_id,
        state=state,
        observed_at_utc=health.observed_at_utc,
        last_success_at_utc=health.last_success_at_utc,
        age_seconds=age_seconds,
        stale_after_seconds=health.stale_after_seconds,
        last_error=health.last_error,
        trade_influence_enabled=False,
    )


@dataclass(frozen=True, slots=True)
class SourceClaim:
    source_id: str
    claim_key: str
    value_fingerprint: str
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "claim_key",
            "value_fingerprint",
        ):
            _canonical_text(name, getattr(self, name))
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CrossSourceConflictAssessment:
    claim_key: str
    state: str
    source_ids: tuple[str, ...]
    value_fingerprints: tuple[str, ...]
    assessed_at_utc: datetime
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        _canonical_text("claim_key", self.claim_key)
        if self.state not in CONFLICT_STATES:
            raise ValueError("invalid conflict state")
        if self.assessed_at_utc.tzinfo is None:
            raise ValueError("assessed_at_utc must be timezone-aware")
        if not isinstance(self.source_ids, tuple):
            raise ValueError("source_ids must be an immutable tuple")
        if not isinstance(self.value_fingerprints, tuple):
            raise ValueError(
                "value_fingerprints must be an immutable tuple"
            )
        if self.trade_influence_enabled is not False:
            raise ValueError(
                "conflict assessment cannot enable trade influence"
            )


def assess_cross_source_conflict(
    claim_key: str,
    claims: tuple[SourceClaim, ...],
    *,
    assessed_at_utc: datetime,
) -> CrossSourceConflictAssessment:
    _canonical_text("claim_key", claim_key)
    if assessed_at_utc.tzinfo is None:
        raise ValueError("assessed_at_utc must be timezone-aware")
    if not isinstance(claims, tuple):
        raise ValueError("claims must be an immutable tuple")

    relevant = tuple(
        claim for claim in claims if claim.claim_key == claim_key
    )
    source_ids = tuple(sorted({claim.source_id for claim in relevant}))
    fingerprints = tuple(
        sorted({claim.value_fingerprint for claim in relevant})
    )

    if len(source_ids) < 2:
        state = "insufficient"
    elif len(fingerprints) == 1:
        state = "aligned"
    else:
        state = "conflict"

    return CrossSourceConflictAssessment(
        claim_key=claim_key,
        state=state,
        source_ids=source_ids,
        value_fingerprints=fingerprints,
        assessed_at_utc=assessed_at_utc,
        trade_influence_enabled=False,
    )
