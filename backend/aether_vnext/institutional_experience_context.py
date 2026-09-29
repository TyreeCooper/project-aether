"""Unified research-only experience context for AETHER vNext Phase 14."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.engine import Connection

from aether_vnext.experience_archive import (
    CrisisRegimeArchiveEntry,
    CrisisRegimeArchiveQuery,
)
from aether_vnext.experience_archive_store import query_crisis_regime_archive
from aether_vnext.failure_history import FailureHistory, FailureHistoryQuery, load_failure_history
from aether_vnext.institutional_analogs import (
    HistoricalDecisionContext,
    HistoricalDecisionContextQuery,
)
from aether_vnext.institutional_memory_query import load_historical_decision_context
from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class InstitutionalExperienceQuery:
    as_of_utc: datetime
    route_id: str | None = None
    playbook_id: str | None = None
    playbook_version: str | None = None
    configuration_hash: str | None = None
    relevance_tags: tuple[str, ...] = ()
    failure_categories: tuple[str, ...] = ()
    crisis_categories: tuple[str, ...] = ()
    crisis_asset_ids: tuple[str, ...] = ()
    crisis_regime_ids: tuple[str, ...] = ()
    memory_limit: int = 50
    failure_limit: int = 50
    crisis_limit: int = 50

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        for name in ("memory_limit", "failure_limit", "crisis_limit"):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class InstitutionalExperienceContext:
    as_of_utc: datetime
    decision_context: HistoricalDecisionContext
    failure_history: FailureHistory
    crisis_regime_entries: tuple[CrisisRegimeArchiveEntry, ...]
    research_only: bool = True
    trade_influence_allowed: bool = False
    independent_evidence_credit: bool = False

    def __post_init__(self) -> None:
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if self.decision_context.as_of_utc != self.as_of_utc:
            raise ValueError("decision context must share the same as_of_utc")
        if self.failure_history.as_of_utc != self.as_of_utc:
            raise ValueError("failure history must share the same as_of_utc")
        if self.research_only is not True:
            raise ValueError("institutional experience context is research_only")
        if self.trade_influence_allowed is not False:
            raise ValueError("institutional experience context cannot influence trades")
        if self.independent_evidence_credit is not False:
            raise ValueError(
                "institutional experience context cannot receive independent evidence credit"
            )


def load_institutional_experience_context(
    conn: Connection,
    *,
    store: VNextStore,
    query: InstitutionalExperienceQuery,
) -> InstitutionalExperienceContext:
    """Build one no-lookahead context from durable memory, failure, and crisis books."""
    decision_context = load_historical_decision_context(
        conn,
        store=store,
        query=HistoricalDecisionContextQuery(
            as_of_utc=query.as_of_utc,
            route_id=query.route_id,
            playbook_id=query.playbook_id,
            playbook_version=query.playbook_version,
            configuration_hash=query.configuration_hash,
            relevance_tags=query.relevance_tags,
            limit=query.memory_limit,
        ),
    )

    failure_history = load_failure_history(
        conn,
        store=store,
        query=FailureHistoryQuery(
            as_of_utc=query.as_of_utc,
            categories=query.failure_categories,
            memory_ids=decision_context.matched_memory_ids,
            trade_ids=decision_context.matched_trade_ids,
            limit=query.failure_limit,
        ),
    )

    crisis_regime_entries = query_crisis_regime_archive(
        conn,
        store=store,
        query=CrisisRegimeArchiveQuery(
            as_of_utc=query.as_of_utc,
            categories=query.crisis_categories,
            asset_ids=query.crisis_asset_ids,
            regime_ids=query.crisis_regime_ids,
            limit=query.crisis_limit,
        ),
    )

    return InstitutionalExperienceContext(
        as_of_utc=query.as_of_utc,
        decision_context=decision_context,
        failure_history=failure_history,
        crisis_regime_entries=crisis_regime_entries,
    )
