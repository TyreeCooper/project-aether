from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.historical_time_binding import (
    HistoricalTimestampBinding,
    ProviderTimestampRole,
    normalize_historical_provider_time,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _binding(
    *,
    role: ProviderTimestampRole,
    source: str = "provider-history",
    interval_seconds: int = 900,
    availability_lag_seconds: int = 2,
) -> HistoricalTimestampBinding:
    return HistoricalTimestampBinding(
        binding_id="reviewed-provider-time-v1",
        provider_source_id=source,
        interval_seconds=interval_seconds,
        timestamp_role=role,
        availability_lag_seconds=availability_lag_seconds,
        reviewed_source_ref="provider-doc:reviewed:2026-09-28",
    )


def test_bucket_open_binding_derives_close_and_availability() -> None:
    result = normalize_historical_provider_time(
        provider_timestamp_utc=T0,
        provider_source_id="provider-history",
        binding=_binding(role=ProviderTimestampRole.BUCKET_OPEN),
    )

    assert result.bucket_open_utc == T0
    assert result.bucket_close_utc == T0 + timedelta(minutes=15)
    assert result.available_at_utc == (
        T0 + timedelta(minutes=15, seconds=2)
    )
    assert result.binding_id == "reviewed-provider-time-v1"


def test_bucket_close_binding_derives_open_without_guessing() -> None:
    result = normalize_historical_provider_time(
        provider_timestamp_utc=T0,
        provider_source_id="provider-history",
        binding=_binding(role=ProviderTimestampRole.BUCKET_CLOSE),
    )

    assert result.bucket_close_utc == T0
    assert result.bucket_open_utc == T0 - timedelta(minutes=15)
    assert result.available_at_utc == T0 + timedelta(seconds=2)


def test_zero_availability_lag_is_explicitly_supported() -> None:
    result = normalize_historical_provider_time(
        provider_timestamp_utc=T0,
        provider_source_id="provider-history",
        binding=_binding(
            role=ProviderTimestampRole.BUCKET_CLOSE,
            availability_lag_seconds=0,
        ),
    )
    assert result.available_at_utc == result.bucket_close_utc


def test_provider_source_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="does not match"):
        normalize_historical_provider_time(
            provider_timestamp_utc=T0,
            provider_source_id="wrong-provider",
            binding=_binding(role=ProviderTimestampRole.BUCKET_OPEN),
        )


def test_unreviewed_or_invalid_binding_values_fail_closed() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        HistoricalTimestampBinding(
            binding_id="binding",
            provider_source_id="provider-history",
            interval_seconds=0,
            timestamp_role=ProviderTimestampRole.BUCKET_OPEN,
            availability_lag_seconds=0,
            reviewed_source_ref="reviewed-ref",
        )

    with pytest.raises(ValueError, match="nonnegative integer"):
        HistoricalTimestampBinding(
            binding_id="binding",
            provider_source_id="provider-history",
            interval_seconds=60,
            timestamp_role=ProviderTimestampRole.BUCKET_OPEN,
            availability_lag_seconds=-1,
            reviewed_source_ref="reviewed-ref",
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_historical_provider_time(
            provider_timestamp_utc=datetime(2026, 9, 28, 12, 0),
            provider_source_id="provider-history",
            binding=_binding(role=ProviderTimestampRole.BUCKET_OPEN),
        )
