"""Canonical AETHER vNext market-data decision pipeline.

This is infrastructure, not a trading seat. It resolves configured sources into one
MarketObservation and refuses to produce an executable observation when source,
freshness, book, or calendar truth is unusable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from aether_vnext.calendars import CalendarDecision
from aether_vnext.domain import MarketObservation
from aether_vnext.market_data import RawQuote, SourceSelection, select_source
from aether_vnext.market_truth import observation_is_valid
from aether_vnext.registry import ProductRegistryRow


@dataclass(frozen=True, slots=True)
class MarketPipelineResult:
    asset_id: str
    observation: MarketObservation | None
    executable: bool
    reason: str
    attempted_sources: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()


class MarketDataPipeline:
    def __init__(
        self,
        *,
        registry: Mapping[str, ProductRegistryRow],
    ) -> None:
        self._registry = registry

    def evaluate(
        self,
        *,
        asset_id: str,
        quotes: Iterable[RawQuote],
        calendar: CalendarDecision,
        as_of_utc: datetime,
    ) -> MarketPipelineResult:
        aid = str(asset_id).strip().lower()
        row = self._registry.get(aid)
        if row is None:
            return MarketPipelineResult(
                asset_id=aid,
                observation=None,
                executable=False,
                reason="unsupported_product",
            )
        if not row.market_data_ready():
            return MarketPipelineResult(
                asset_id=aid,
                observation=None,
                executable=False,
                reason="market_data_unbound",
            )
        assert row.stale_threshold_ms is not None
        selection: SourceSelection = select_source(
            quotes,
            registry_row=row,
            calendar=calendar,
            as_of_utc=as_of_utc,
            stale_threshold_ms=row.stale_threshold_ms,
        )
        observation = selection.observation
        if observation is None:
            reason = _selection_failure_reason(selection)
            return MarketPipelineResult(
                asset_id=aid,
                observation=None,
                executable=False,
                reason=reason,
                attempted_sources=selection.attempted_sources,
                rejection_reasons=selection.rejection_reasons,
            )

        if not observation_is_valid(
            observation,
            max_age_ms=row.stale_threshold_ms,
        ):
            return MarketPipelineResult(
                asset_id=aid,
                observation=observation,
                executable=False,
                reason=(
                    "session_closed"
                    if not calendar.eligible
                    else "market_invalid"
                ),
                attempted_sources=selection.attempted_sources,
                rejection_reasons=selection.rejection_reasons,
            )

        return MarketPipelineResult(
            asset_id=aid,
            observation=observation,
            executable=True,
            reason="market_valid",
            attempted_sources=selection.attempted_sources,
            rejection_reasons=selection.rejection_reasons,
        )


def _selection_failure_reason(selection: SourceSelection) -> str:
    reasons = selection.rejection_reasons
    if any(reason.endswith(":stale") for reason in reasons):
        return "quote_stale"
    if any(reason.endswith(":invalid") for reason in reasons):
        return "market_invalid"
    if reasons and all(reason.endswith(":missing") for reason in reasons):
        return "quote_missing"
    return "market_unavailable"
