"""AETHER vNext News-Market Intelligence contracts from Pre-Code Freeze F-007."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class NewsSource:
    source_id: str
    source_name: str
    source_class: str
    primary_or_secondary: str
    authority_class: str
    base_timezone: str
    provider_adapter_id: str
    active: bool
    terms_licensing_metadata_ref: str | None

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "source_name",
            "source_class",
            "primary_or_secondary",
            "authority_class",
            "base_timezone",
            "provider_adapter_id",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if not isinstance(self.active, bool):
            raise ValueError("active must be boolean")
        if self.terms_licensing_metadata_ref is not None and (
            not isinstance(self.terms_licensing_metadata_ref, str)
            or not self.terms_licensing_metadata_ref
            or self.terms_licensing_metadata_ref
            != self.terms_licensing_metadata_ref.strip()
        ):
            raise ValueError(
                "terms_licensing_metadata_ref must be canonical text when present"
            )


@dataclass(frozen=True, slots=True)
class RawNewsItem:
    news_item_id: str
    source_id: str
    provider_item_id: str | None
    canonical_url: str | None
    title: str
    body_hash: str
    published_at_utc: datetime
    first_seen_at_utc: datetime
    received_at_utc: datetime
    revision_of_news_item_id: str | None
    correction_or_retraction: bool
    language: str
    ingest_status: str
    dedupe_key: str
    raw_payload_ref: str

    def __post_init__(self) -> None:
        for name in (
            "news_item_id",
            "source_id",
            "title",
            "body_hash",
            "language",
            "ingest_status",
            "dedupe_key",
            "raw_payload_ref",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        for name in (
            "provider_item_id",
            "canonical_url",
            "revision_of_news_item_id",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text when present")
        for name in (
            "published_at_utc",
            "first_seen_at_utc",
            "received_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not isinstance(self.correction_or_retraction, bool):
            raise ValueError("correction_or_retraction must be boolean")


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    event_id: str
    event_cluster_id: str
    event_type: str
    source_news_item_ids: tuple[str, ...]
    assets: tuple[str, ...]
    clusters: tuple[str, ...]
    canonical_event_at_utc: datetime
    information_available_at_utc: datetime
    scheduled: bool
    expected: bool | None
    consensus: float | str | None
    actual: float | str | None
    surprise_magnitude: float | None
    direction: str | None
    severity: float | None
    novelty: float | None
    confidence: float | None
    market_scope: str
    company_specific: bool = False
    sector_specific: bool = False
    macro: bool = False
    geopolitical: bool = False
    regulatory: bool = False
    earnings: bool = False
    policy: bool = False
    supply: bool = False
    demand: bool = False
    liquidity: bool = False
    normalizer_version: str = ""

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "event_cluster_id",
            "event_type",
            "market_scope",
            "normalizer_version",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        for name in ("source_news_item_ids", "assets", "clusters"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ValueError(f"{name} must be an immutable tuple")
            for value in values:
                if (
                    not isinstance(value, str)
                    or not value
                    or value != value.strip()
                ):
                    raise ValueError(
                        f"{name} entries must be canonical text"
                    )
        for name in (
            "canonical_event_at_utc",
            "information_available_at_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not isinstance(self.scheduled, bool):
            raise ValueError("scheduled must be boolean")
        if self.expected is not None and not isinstance(self.expected, bool):
            raise ValueError("expected must be boolean when present")
        for name in (
            "company_specific",
            "sector_specific",
            "macro",
            "geopolitical",
            "regulatory",
            "earnings",
            "policy",
            "supply",
            "demand",
            "liquidity",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        for name in ("consensus", "actual"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(f"{name} must not be boolean")
            if isinstance(value, str):
                if not value or value != value.strip():
                    raise ValueError(f"{name} text must be canonical")
            elif not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite when numeric")
        for name in (
            "surprise_magnitude",
            "severity",
            "novelty",
            "confidence",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"{name} must be finite when present")
        if self.direction is not None and (
            not isinstance(self.direction, str)
            or not self.direction
            or self.direction != self.direction.strip()
        ):
            raise ValueError("direction must be canonical text when present")


@dataclass(frozen=True, slots=True)
class EventAssetLink:
    event_id: str
    asset_id: str
    relation_type: str
    confidence: float
    evidence_source_ids: tuple[str, ...]
    created_at_utc: datetime
    linker_version: str

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "asset_id",
            "relation_type",
            "linker_version",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if (
            not isinstance(self.evidence_source_ids, tuple)
            or any(
                not isinstance(value, str)
                or not value
                or value != value.strip()
                for value in self.evidence_source_ids
            )
        ):
            raise ValueError(
                "evidence_source_ids must be an immutable tuple of canonical text"
            )
        if isinstance(self.confidence, bool) or not math.isfinite(
            float(self.confidence)
        ):
            raise ValueError("confidence must be finite")
        if self.created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EventMarketResponse:
    event_id: str
    asset_id: str
    pre_event_observation_id: str
    return_1m: float | None
    return_5m: float | None
    return_15m: float | None
    return_1h: float | None
    return_4h: float | None
    return_1d: float | None
    mfe: float | None
    mae: float | None
    realized_vol_change: float | None
    volume_change: float | None
    spread_change: float | None
    liquidity_change: float | None
    correlation_change: float | None
    continuation_or_reversal: str | None
    stabilization_time: float | None
    market_data_version: str


@dataclass(frozen=True, slots=True)
class HistoricalAnalogRun:
    analog_run_id: str
    query_event_or_state_id: str
    feature_spec_version: str
    as_of_utc: datetime
    eligible_history_cutoff_utc: datetime
    matched_event_ids: tuple[str, ...]
    similarity_scores: tuple[float, ...]
    outcome_distribution: dict[str, Any]
    created_at_utc: datetime
    research_only: bool = True

    def __post_init__(self) -> None:
        if self.research_only is not True:
            raise ValueError("historical analog output is research_only")
        if len(self.matched_event_ids) != len(self.similarity_scores):
            raise ValueError("matched_event_ids and similarity_scores must align")
        if self.eligible_history_cutoff_utc > self.as_of_utc:
            raise ValueError("history cutoff cannot be after as_of_utc")


def raw_news_identity_key(
    *,
    source_id: str,
    provider_item_id: str | None,
    canonical_url: str | None,
    published_at_utc: datetime,
    normalized_title: str,
) -> str:
    """Return the frozen F-007 SHA-256 raw-item identity key."""
    for name, value in (
        ("source_id", source_id),
        ("normalized_title", normalized_title),
    ):
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
        ):
            raise ValueError(f"{name} must be canonical text")
    for name, value in (
        ("provider_item_id", provider_item_id),
        ("canonical_url", canonical_url),
    ):
        if value is not None and (
            not isinstance(value, str)
            or not value
            or value != value.strip()
        ):
            raise ValueError(f"{name} must be canonical text when present")
    if published_at_utc.tzinfo is None:
        raise ValueError("published_at_utc must be timezone-aware")
    if provider_item_id:
        material = f"{source_id}|{provider_item_id}"
    else:
        material = (
            f"{source_id}|{canonical_url or ''}|"
            f"{published_at_utc.isoformat()}|{normalized_title}"
        )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
