"""Historical crisis and regime archive contracts for AETHER vNext Phase 14."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


CRISIS_REGIME_CATEGORIES = frozenset(
    {
        "crash_flash_crash",
        "volatility_expansion_compression",
        "liquidity_crisis",
        "rate_inflation_shock",
        "geopolitical_shock",
        "bank_exchange_failure",
        "commodity_shock",
        "earnings_guidance_gap",
        "regulatory_shock",
        "crypto_failure_venue_incident",
        "policy_reversal",
        "scheduled_macro_surprise",
    }
)


def _canonical_tuple(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an immutable tuple")
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{name} entries must be canonical text")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class CrisisRegimeArchiveEntry:
    archive_id: str
    category: str
    episode_ref: str
    asset_ids: tuple[str, ...]
    regime_ids: tuple[str, ...]
    started_at_utc: datetime
    ended_at_utc: datetime
    recorded_at_utc: datetime
    source_record_ids: tuple[str, ...]
    synthetic: bool = False
    research_only: bool = True

    def __post_init__(self) -> None:
        for name in ("archive_id", "episode_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be canonical text")
        if self.category not in CRISIS_REGIME_CATEGORIES:
            raise ValueError("invalid crisis/regime category")
        _canonical_tuple("asset_ids", self.asset_ids)
        _canonical_tuple("regime_ids", self.regime_ids)
        _canonical_tuple("source_record_ids", self.source_record_ids)
        for name in ("started_at_utc", "ended_at_utc", "recorded_at_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("crisis/regime episode time range is reversed")
        if self.recorded_at_utc < self.started_at_utc:
            raise ValueError("archive cannot be recorded before episode start")
        if not isinstance(self.synthetic, bool):
            raise ValueError("synthetic must be boolean")
        if self.research_only is not True:
            raise ValueError("crisis/regime archive is research_only")


@dataclass(frozen=True, slots=True)
class CrisisRegimeArchiveQuery:
    as_of_utc: datetime
    categories: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    regime_ids: tuple[str, ...] = ()
    limit: int = 20

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        _canonical_tuple("categories", self.categories)
        _canonical_tuple("asset_ids", self.asset_ids)
        _canonical_tuple("regime_ids", self.regime_ids)
        if any(value not in CRISIS_REGIME_CATEGORIES for value in self.categories):
            raise ValueError("invalid crisis/regime query category")
        if (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or self.limit <= 0
        ):
            raise ValueError("limit must be a positive integer")


def retrieve_crisis_regime_archive(
    *,
    query: CrisisRegimeArchiveQuery,
    entries: Iterable[CrisisRegimeArchiveEntry],
) -> tuple[CrisisRegimeArchiveEntry, ...]:
    """Return point-in-time eligible archive entries using explicit filters only."""
    category_filter = set(query.categories)
    asset_filter = set(query.asset_ids)
    regime_filter = set(query.regime_ids)
    matches: list[CrisisRegimeArchiveEntry] = []

    for entry in entries:
        if entry.recorded_at_utc > query.as_of_utc:
            continue
        if category_filter and entry.category not in category_filter:
            continue
        if asset_filter and asset_filter.isdisjoint(entry.asset_ids):
            continue
        if regime_filter and regime_filter.isdisjoint(entry.regime_ids):
            continue
        matches.append(entry)

    matches.sort(
        key=lambda row: (
            row.recorded_at_utc,
            row.ended_at_utc,
            row.archive_id,
        ),
        reverse=True,
    )
    return tuple(matches[: query.limit])
