"""Reviewed historical provider-timestamp semantics for AETHER vNext.

This module exists so provider historical bars can be normalized without guessing
whether the provider timestamp denotes bucket open or bucket close, and without
guessing historical availability latency.

A binding is a reviewed external/source fact. AETHER supplies no provider defaults.
Without a reviewed binding, IBKR/NinjaTrader historical bars remain raw and may not
enter the immutable PIT research warehouse through this path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class ProviderTimestampRole(StrEnum):
    BUCKET_OPEN = "bucket_open"
    BUCKET_CLOSE = "bucket_close"


@dataclass(frozen=True, slots=True)
class HistoricalTimestampBinding:
    binding_id: str
    provider_source_id: str
    interval_seconds: int
    timestamp_role: ProviderTimestampRole
    availability_lag_seconds: int
    reviewed_source_ref: str

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "provider_source_id",
            "reviewed_source_ref",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")
        if (
            not isinstance(self.interval_seconds, int)
            or isinstance(self.interval_seconds, bool)
            or self.interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be a positive integer")
        if (
            not isinstance(self.availability_lag_seconds, int)
            or isinstance(self.availability_lag_seconds, bool)
            or self.availability_lag_seconds < 0
        ):
            raise ValueError(
                "availability_lag_seconds must be a nonnegative integer"
            )
        if not isinstance(self.timestamp_role, ProviderTimestampRole):
            raise ValueError(
                "timestamp_role must be a ProviderTimestampRole"
            )


@dataclass(frozen=True, slots=True)
class NormalizedHistoricalBarTime:
    provider_timestamp_utc: datetime
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    available_at_utc: datetime
    binding_id: str
    reviewed_source_ref: str


def normalize_historical_provider_time(
    *,
    provider_timestamp_utc: datetime,
    provider_source_id: str,
    binding: HistoricalTimestampBinding,
) -> NormalizedHistoricalBarTime:
    """Normalize one reviewed provider timestamp into PIT bar boundaries."""
    if provider_timestamp_utc.tzinfo is None:
        raise ValueError("provider_timestamp_utc must be timezone-aware")
    source = str(provider_source_id).strip()
    if not source:
        raise ValueError("provider_source_id is required")
    if source != binding.provider_source_id:
        raise ValueError(
            "provider_source_id does not match reviewed timestamp binding"
        )

    interval = timedelta(seconds=binding.interval_seconds)
    if binding.timestamp_role is ProviderTimestampRole.BUCKET_OPEN:
        opened = provider_timestamp_utc
        closed = opened + interval
    elif binding.timestamp_role is ProviderTimestampRole.BUCKET_CLOSE:
        closed = provider_timestamp_utc
        opened = closed - interval
    else:
        raise ValueError("unsupported provider timestamp role")

    available = closed + timedelta(
        seconds=binding.availability_lag_seconds
    )
    return NormalizedHistoricalBarTime(
        provider_timestamp_utc=provider_timestamp_utc,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        available_at_utc=available,
        binding_id=binding.binding_id,
        reviewed_source_ref=binding.reviewed_source_ref,
    )
