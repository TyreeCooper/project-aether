"""Canonical market-data normalization and source failover for AETHER vNext.

Adapters emit RawQuote objects. This layer turns them into the single
MarketObservation contract used by every later seat. Missing, stale, crossed, or
calendar-ineligible data never becomes a neutral/healthy observation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Iterable

from aether_vnext.calendars import CalendarDecision
from aether_vnext.domain import MarketObservation, QualityState
from aether_vnext.registry import ProductRegistryRow


@dataclass(frozen=True, slots=True)
class RawQuote:
    asset_id: str
    venue: str
    source_id: str
    bid: float | None
    ask: float | None
    last: float | None
    mark: float | None
    exchange_ts: datetime | None
    received_ts: datetime
    adapter_version: str


def _utc_iso(ts: datetime | None) -> str:
    return "" if ts is None else ts.isoformat()


def observation_id_for(
    *,
    raw: RawQuote,
    as_of_utc: datetime,
) -> str:
    material = "|".join(
        (
            raw.asset_id.lower(),
            raw.venue,
            raw.source_id,
            _utc_iso(raw.exchange_ts),
            raw.received_ts.isoformat(),
            as_of_utc.isoformat(),
            str(raw.bid),
            str(raw.ask),
            str(raw.last),
            str(raw.mark),
            raw.adapter_version,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _age_ms(raw: RawQuote, as_of_utc: datetime) -> int:
    if as_of_utc.tzinfo is None or raw.received_ts.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    reference = raw.exchange_ts or raw.received_ts
    if reference.tzinfo is None:
        raise ValueError("exchange_ts must be timezone-aware when provided")
    age_ms = int((as_of_utc - reference).total_seconds() * 1000)
    if age_ms < 0:
        raise ValueError("market timestamp cannot be after decision time")
    return age_ms


def _book_invalid(raw: RawQuote) -> bool:
    for value in (raw.bid, raw.ask, raw.last, raw.mark):
        if value is not None and float(value) <= 0:
            return True
    if raw.bid is not None and raw.ask is not None and raw.bid > raw.ask:
        return True
    return raw.mark is None


def _spread(raw: RawQuote) -> tuple[float | None, float | None]:
    if raw.bid is None or raw.ask is None:
        return None, None
    if raw.bid <= 0 or raw.ask <= 0 or raw.bid > raw.ask:
        return None, None
    spread_abs = float(raw.ask) - float(raw.bid)
    mid = (float(raw.ask) + float(raw.bid)) / 2.0
    if mid <= 0:
        return spread_abs, None
    return spread_abs, (spread_abs / mid) * 10_000.0


def normalize_quote(
    raw: RawQuote,
    *,
    registry_row: ProductRegistryRow,
    calendar: CalendarDecision,
    as_of_utc: datetime,
    stale_threshold_ms: int,
    fallback_reason: str | None = None,
) -> MarketObservation:
    if raw.asset_id.lower() != registry_row.asset_id:
        raise ValueError("raw quote asset_id does not match registry row")
    if stale_threshold_ms <= 0:
        raise ValueError("stale_threshold_ms must be positive")

    age_ms = _age_ms(raw, as_of_utc)
    spread_abs, spread_bps = _spread(raw)

    if _book_invalid(raw):
        quality = QualityState.INVALID
    elif age_ms > stale_threshold_ms:
        quality = QualityState.STALE
    elif fallback_reason is not None:
        quality = QualityState.DEGRADED
    else:
        quality = QualityState.HEALTHY

    # Calendar/session ineligibility does not rewrite quote quality. The
    # observation carries both truths independently.
    return MarketObservation(
        observation_id=observation_id_for(raw=raw, as_of_utc=as_of_utc),
        asset_id=registry_row.asset_id,
        venue=raw.venue,
        bid=raw.bid,
        ask=raw.ask,
        last=raw.last,
        mark=raw.mark,
        source=raw.source_id,
        exchange_ts=raw.exchange_ts,
        received_ts=raw.received_ts,
        age_ms=age_ms,
        spread_abs=spread_abs,
        spread_bps=spread_bps,
        session_state=calendar.session_state,
        quality_state=quality,
        fallback_reason=fallback_reason,
        calendar_state=calendar.calendar_state,
        data_version=raw.adapter_version,
    )


@dataclass(frozen=True, slots=True)
class SourceSelection:
    observation: MarketObservation | None
    attempted_sources: tuple[str, ...]
    rejection_reasons: tuple[str, ...]


def select_source(
    quotes: Iterable[RawQuote],
    *,
    registry_row: ProductRegistryRow,
    calendar: CalendarDecision,
    as_of_utc: datetime,
    stale_threshold_ms: int,
) -> SourceSelection:
    """Select primary, then fallback, without silently neutralizing bad data."""
    # A provider payload may contain multiple assets under one source_id. Select
    # only the requested asset before source precedence is evaluated.
    by_source = {
        quote.source_id: quote
        for quote in quotes
        if quote.asset_id.lower() == registry_row.asset_id
    }
    attempted: list[str] = []
    rejections: list[str] = []

    ordered_sources = [
        registry_row.primary_market_source_id,
        registry_row.fallback_market_source_id,
    ]
    for index, source_id in enumerate(ordered_sources):
        if source_id is None:
            continue
        attempted.append(source_id)
        raw = by_source.get(source_id)
        if raw is None:
            rejections.append(f"{source_id}:missing")
            continue
        observation = normalize_quote(
            raw,
            registry_row=registry_row,
            calendar=calendar,
            as_of_utc=as_of_utc,
            stale_threshold_ms=stale_threshold_ms,
            fallback_reason=(
                None
                if index == 0
                else f"primary_unusable:{registry_row.primary_market_source_id}"
            ),
        )
        if observation.quality_state in {
            QualityState.HEALTHY,
            QualityState.DEGRADED,
        }:
            return SourceSelection(
                observation=observation,
                attempted_sources=tuple(attempted),
                rejection_reasons=tuple(rejections),
            )
        rejections.append(
            f"{source_id}:{observation.quality_state.value}"
        )

    return SourceSelection(
        observation=None,
        attempted_sources=tuple(attempted),
        rejection_reasons=tuple(rejections),
    )
