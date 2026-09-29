"""No-lookahead retrieval for AETHER vNext institutional memory.

Phase 14 may retrieve prior recorded experience as research context, but retrieval
cannot create trading authority or independent evidence. The caller owns any
interpretation of the returned records; this module only applies explicit,
deterministic filters and point-in-time availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from aether_vnext.institutional_memory import InstitutionalMemoryRecord


def _optional_canonical_text(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text when present")
    return value


def _canonical_tags(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError("relevance_tags must be an immutable tuple")
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("relevance_tags entries must be canonical text")
    if len(values) != len(set(values)):
        raise ValueError("relevance_tags cannot contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class HistoricalDecisionContextQuery:
    as_of_utc: datetime
    route_id: str | None = None
    playbook_id: str | None = None
    playbook_version: str | None = None
    configuration_hash: str | None = None
    relevance_tags: tuple[str, ...] = ()
    limit: int = 20

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        for name in (
            "route_id",
            "playbook_id",
            "playbook_version",
            "configuration_hash",
        ):
            _optional_canonical_text(name, getattr(self, name))
        _canonical_tags(self.relevance_tags)
        if (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or self.limit <= 0
        ):
            raise ValueError("limit must be a positive integer")


@dataclass(frozen=True, slots=True)
class HistoricalDecisionContext:
    as_of_utc: datetime
    matched_memory_ids: tuple[str, ...]
    matched_trade_ids: tuple[str, ...]
    matched_recorded_at_utc: tuple[datetime, ...]
    research_only: bool = True
    trade_influence_allowed: bool = False
    independent_evidence_credit: bool = False

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        size = len(self.matched_memory_ids)
        if (
            len(self.matched_trade_ids) != size
            or len(self.matched_recorded_at_utc) != size
        ):
            raise ValueError("historical decision context rows must align")
        if self.research_only is not True:
            raise ValueError("historical decision context is research_only")
        if self.trade_influence_allowed is not False:
            raise ValueError("historical decision context cannot influence trades")
        if self.independent_evidence_credit is not False:
            raise ValueError(
                "historical decision context cannot receive independent evidence credit"
            )


def retrieve_historical_decision_context(
    *,
    query: HistoricalDecisionContextQuery,
    memories: Iterable[InstitutionalMemoryRecord],
) -> HistoricalDecisionContext:
    """Return prior recorded memories that satisfy only caller-declared filters.

    Availability is based on ``recorded_at_utc`` rather than occurrence time so
    a memory that had not yet been recorded at ``as_of_utc`` cannot leak into a
    historical decision context. Results are ordered newest-recorded first with
    deterministic tie-breaking and are always research-only.
    """
    requested_tags = set(query.relevance_tags)
    matches: list[InstitutionalMemoryRecord] = []

    for memory in memories:
        if memory.recorded_at_utc > query.as_of_utc:
            continue
        if query.route_id is not None and memory.route_id != query.route_id:
            continue
        if query.playbook_id is not None and memory.playbook_id != query.playbook_id:
            continue
        if (
            query.playbook_version is not None
            and memory.playbook_version != query.playbook_version
        ):
            continue
        if (
            query.configuration_hash is not None
            and memory.configuration_hash != query.configuration_hash
        ):
            continue
        if requested_tags and requested_tags.isdisjoint(memory.future_relevance):
            continue
        matches.append(memory)

    matches.sort(
        key=lambda row: (
            row.recorded_at_utc,
            row.occurred_at_utc,
            row.memory_id,
        ),
        reverse=True,
    )
    matches = matches[: query.limit]

    return HistoricalDecisionContext(
        as_of_utc=query.as_of_utc,
        matched_memory_ids=tuple(row.memory_id for row in matches),
        matched_trade_ids=tuple(row.trade_id for row in matches),
        matched_recorded_at_utc=tuple(row.recorded_at_utc for row in matches),
    )
