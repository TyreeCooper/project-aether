"""Provider-neutral market ingress and health diagnostics for AETHER vNext.

External adapters own network/provider I/O. This module owns the Firm boundary:
reviewed runtime Product Registry truth, authoritative calendar identity, canonical
MarketDataPipeline normalization, durable MarketObservation persistence, and an
append-only ingress-attempt audit trail.

It does not invent provider credentials, market sources, stale thresholds, calendar
exceptions, futures contracts, or trading opinions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Iterable, Protocol

from sqlalchemy.engine import Connection

from aether_vnext.calendars import (
    CalendarException,
    CalendarExceptionProvider,
    calendar_decision,
)
from aether_vnext.domain import MarketObservation, QualityState
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.market_data import RawQuote
from aether_vnext.market_pipeline import MarketDataPipeline
from aether_vnext.registry import registry_row
from aether_vnext.registry_runtime import (
    binding_blockers,
    materialize_bound_registry_row,
)
from aether_vnext.store import VNextStore


class IdentifiedCalendarProvider(CalendarExceptionProvider, Protocol):
    provider_id: str

    def exception_for(
        self,
        *,
        calendar_id: str,
        session_date: date,
    ) -> CalendarException | None: ...


@dataclass(frozen=True, slots=True)
class MarketIngressResult:
    attempt_id: str
    asset_id: str
    runtime_registry_binding_hash: str | None
    observation: MarketObservation | None
    executable: bool
    reason: str
    calendar_reason: str | None
    attempted_sources: tuple[str, ...]
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketIngressHealth:
    asset_id: str
    binding_present: bool
    binding_ready: bool
    latest_attempt_id: str | None
    latest_attempt_at_utc: datetime | None
    latest_attempt_executable: bool | None
    latest_reason: str
    observation_id: str | None
    observation_age_now_ms: int | None
    fresh_now: bool
    blockers: tuple[str, ...]


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _calendar_provider_id(
    provider: IdentifiedCalendarProvider | None,
) -> str | None:
    if provider is None:
        return None
    value = str(getattr(provider, "provider_id", "") or "").strip()
    return value or None


def _attempt_id(
    *,
    asset_id: str,
    binding_hash: str | None,
    as_of_utc: datetime,
    calendar_provider_id: str | None,
    quote_ids: tuple[tuple[str, str, str], ...],
) -> str:
    return _canonical_hash(
        {
            "asset_id": asset_id,
            "binding_hash": binding_hash,
            "as_of_utc": as_of_utc.isoformat(),
            "calendar_provider_id": calendar_provider_id,
            "quotes": list(quote_ids),
        }
    )


def _quote_identity(quotes: Iterable[RawQuote]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                str(quote.source_id),
                (
                    quote.exchange_ts.isoformat()
                    if quote.exchange_ts is not None
                    else ""
                ),
                quote.received_ts.isoformat(),
            )
            for quote in quotes
        )
    )


def ingest_market_quotes(
    conn: Connection,
    store: VNextStore,
    *,
    asset_id: str,
    quotes: Iterable[RawQuote],
    calendar_provider: IdentifiedCalendarProvider | None,
    as_of_utc: datetime,
    created_at_utc: datetime | None = None,
) -> MarketIngressResult:
    """Normalize and persist one asset's provider-neutral market-ingress attempt."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    created = as_of_utc if created_at_utc is None else created_at_utc
    if created.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")

    aid = str(asset_id).strip().lower()
    base = registry_row(aid)
    quote_rows = tuple(quotes)
    provider_id = _calendar_provider_id(calendar_provider)

    runtime = store.load_runtime_registry_binding(conn, asset_id=aid)
    binding_hash = (
        None if runtime is None else str(runtime["binding_hash"])
    )
    attempt_id = _attempt_id(
        asset_id=aid,
        binding_hash=binding_hash,
        as_of_utc=as_of_utc,
        calendar_provider_id=provider_id,
        quote_ids=_quote_identity(quote_rows),
    )

    def finish(
        *,
        observation: MarketObservation | None,
        executable: bool,
        reason: str,
        calendar_reason: str | None,
        attempted_sources: tuple[str, ...] = (),
        rejection_reasons: tuple[str, ...] = (),
    ) -> MarketIngressResult:
        if observation is not None:
            store.record_market_observation(conn, observation)
        store.record_market_ingress_attempt(
            conn,
            attempt_id=attempt_id,
            asset_id=aid,
            configuration_hash=CONFIGURATION_HASH,
            runtime_registry_binding_hash=binding_hash,
            as_of_utc=as_of_utc,
            calendar_id=base.calendar_id,
            calendar_provider_id=provider_id,
            observation_id=(
                None
                if observation is None
                else observation.observation_id
            ),
            executable=executable,
            reason=reason,
            attempted_sources=attempted_sources,
            rejection_reasons=rejection_reasons,
            created_at_utc=created,
        )
        return MarketIngressResult(
            attempt_id=attempt_id,
            asset_id=aid,
            runtime_registry_binding_hash=binding_hash,
            observation=observation,
            executable=executable,
            reason=reason,
            calendar_reason=calendar_reason,
            attempted_sources=attempted_sources,
            rejection_reasons=rejection_reasons,
        )

    if runtime is None:
        return finish(
            observation=None,
            executable=False,
            reason="runtime_product_binding_missing",
            calendar_reason=None,
        )
    if runtime["configuration_hash"] != CONFIGURATION_HASH:
        return finish(
            observation=None,
            executable=False,
            reason="runtime_product_binding_configuration_mismatch",
            calendar_reason=None,
        )

    binding = runtime["binding"]
    runtime_blockers = binding_blockers(binding, as_of_utc=as_of_utc)
    if runtime_blockers:
        return finish(
            observation=None,
            executable=False,
            reason="runtime_product_binding_unready",
            calendar_reason=None,
            rejection_reasons=runtime_blockers,
        )

    row = materialize_bound_registry_row(binding, as_of_utc=as_of_utc)

    if base.calendar_id != "crypto_24x7":
        expected_provider_id = str(binding.calendar_provider_id or "").strip()
        if calendar_provider is None:
            return finish(
                observation=None,
                executable=False,
                reason="calendar_provider_unavailable",
                calendar_reason="calendar_exception_provider_required",
                rejection_reasons=(
                    f"calendar_provider_expected:{expected_provider_id}",
                ),
            )
        if provider_id != expected_provider_id:
            return finish(
                observation=None,
                executable=False,
                reason="calendar_provider_identity_mismatch",
                calendar_reason=None,
                rejection_reasons=(
                    f"expected:{expected_provider_id}",
                    f"received:{provider_id or ''}",
                ),
            )

    calendar = calendar_decision(
        calendar_id=row.calendar_id,
        at_utc=as_of_utc,
        exception_provider=calendar_provider,
    )
    pipeline = MarketDataPipeline(registry={aid: row})
    evaluated = pipeline.evaluate(
        asset_id=aid,
        quotes=quote_rows,
        calendar=calendar,
        as_of_utc=as_of_utc,
    )
    return finish(
        observation=evaluated.observation,
        executable=evaluated.executable,
        reason=evaluated.reason,
        calendar_reason=calendar.reason,
        attempted_sources=evaluated.attempted_sources,
        rejection_reasons=evaluated.rejection_reasons,
    )


def assess_market_ingress_health(
    conn: Connection,
    store: VNextStore,
    *,
    asset_id: str,
    as_of_utc: datetime,
) -> MarketIngressHealth:
    """Read latest durable ingress truth without making a provider call."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    aid = str(asset_id).strip().lower()

    runtime = store.load_runtime_registry_binding(conn, asset_id=aid)
    if runtime is None:
        return MarketIngressHealth(
            asset_id=aid,
            binding_present=False,
            binding_ready=False,
            latest_attempt_id=None,
            latest_attempt_at_utc=None,
            latest_attempt_executable=None,
            latest_reason="runtime_product_binding_missing",
            observation_id=None,
            observation_age_now_ms=None,
            fresh_now=False,
            blockers=("runtime_product_binding_missing",),
        )

    binding = runtime["binding"]
    blockers = binding_blockers(binding, as_of_utc=as_of_utc)
    latest = store.latest_market_ingress_attempt(conn, asset_id=aid)
    if latest is None:
        return MarketIngressHealth(
            asset_id=aid,
            binding_present=True,
            binding_ready=not blockers,
            latest_attempt_id=None,
            latest_attempt_at_utc=None,
            latest_attempt_executable=None,
            latest_reason="market_ingress_not_observed",
            observation_id=None,
            observation_age_now_ms=None,
            fresh_now=False,
            blockers=blockers + ("market_ingress_not_observed",),
        )

    observation_id = (
        None
        if latest["observation_id"] is None
        else str(latest["observation_id"])
    )
    observation = (
        None
        if observation_id is None
        else store.load_market_observation(
            conn,
            observation_id=observation_id,
        )
    )
    age_now_ms: int | None = None
    fresh_now = False
    health_blockers = list(blockers)
    if observation is None:
        health_blockers.append("latest_ingress_has_no_observation")
    else:
        reference = observation.exchange_ts or observation.received_ts
        age_now_ms = int((as_of_utc - reference).total_seconds() * 1000)
        if age_now_ms < 0:
            health_blockers.append("observation_timestamp_in_future")
        elif binding.stale_threshold_ms is None:
            health_blockers.append("stale_threshold_missing")
        elif age_now_ms > binding.stale_threshold_ms:
            health_blockers.append("latest_observation_stale_now")
        elif observation.quality_state is not QualityState.HEALTHY:
            health_blockers.append(
                f"latest_observation_quality:{observation.quality_state.value}"
            )
        else:
            fresh_now = True

    return MarketIngressHealth(
        asset_id=aid,
        binding_present=True,
        binding_ready=not blockers,
        latest_attempt_id=str(latest["attempt_id"]),
        latest_attempt_at_utc=latest["as_of_utc"],
        latest_attempt_executable=bool(latest["executable"]),
        latest_reason=str(latest["reason"]),
        observation_id=observation_id,
        observation_age_now_ms=age_now_ms,
        fresh_now=fresh_now,
        blockers=tuple(dict.fromkeys(health_blockers)),
    )
