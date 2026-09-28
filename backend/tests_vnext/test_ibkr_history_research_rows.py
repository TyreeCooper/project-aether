from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.historical_time_binding import (
    HistoricalTimestampBinding,
    ProviderTimestampRole,
)
from aether_vnext.ibkr_history_research_rows import (
    ibkr_research_manifest_bar_rows,
)
from aether_vnext.ibkr_webapi_history import (
    IBKR_HISTORY_SOURCE_ID,
    IbkrHistoricalBar,
    IbkrHistoricalBatch,
)


UTC = timezone.utc
T0 = datetime(2025, 5, 14, 13, 30, tzinfo=UTC)


def _bar(
    *,
    provider_timestamp_utc: datetime = T0,
    fetched_at_utc: datetime | None = None,
) -> IbkrHistoricalBar:
    return IbkrHistoricalBar(
        asset_id="nvda",
        contract_id=265598,
        provider_timestamp_utc=provider_timestamp_utc,
        open=212.09,
        high=213.94,
        low=210.58,
        close=212.11,
        volume=100.0,
        source_id=IBKR_HISTORY_SOURCE_ID,
        source_data_version="ibkr-history-fetch-v1",
        source_ref="ibkr:reviewed-request:1",
        fetched_at_utc=(
            fetched_at_utc
            if fetched_at_utc is not None
            else T0 + timedelta(days=5)
        ),
    )


def _batch(bar: IbkrHistoricalBar) -> IbkrHistoricalBatch:
    return IbkrHistoricalBatch(
        asset_id="nvda",
        contract_id=265598,
        symbol="NVDA",
        text="NVIDIA CORP",
        requested_period="1w",
        requested_bar="1d",
        requested_source="Last",
        outside_rth=False,
        md_availability="S",
        market_data_delay_ms=0,
        reported_points=1,
        price_factor=100.0,
        volume_factor=100.0,
        timestamp_unit="epoch_milliseconds",
        bars=(bar,),
    )


def _binding(
    *,
    role: ProviderTimestampRole,
    interval_seconds: int = 86400,
    availability_lag_seconds: int = 1,
    provider_source_id: str = IBKR_HISTORY_SOURCE_ID,
) -> HistoricalTimestampBinding:
    return HistoricalTimestampBinding(
        binding_id="ibkr-reviewed-time-v1",
        provider_source_id=provider_source_id,
        interval_seconds=interval_seconds,
        timestamp_role=role,
        availability_lag_seconds=availability_lag_seconds,
        reviewed_source_ref="ibkr-doc:timestamp-semantics:reviewed",
    )


def test_close_timestamp_binding_creates_research_row() -> None:
    rows = ibkr_research_manifest_bar_rows(
        _batch(_bar()),
        timestamp_binding=_binding(
            role=ProviderTimestampRole.BUCKET_CLOSE,
        ),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["asset_id"] == "nvda"
    assert row["interval_seconds"] == 86400
    assert row["bucket_close_utc"] == T0.isoformat()
    assert row["bucket_open_utc"] == (
        T0 - timedelta(days=1)
    ).isoformat()
    assert row["available_at_utc"] == (
        T0 + timedelta(seconds=1)
    ).isoformat()
    assert row["open"] == pytest.approx(212.09)
    assert row["close"] == pytest.approx(212.11)
    assert "ibkr-reviewed-time-v1" in str(row["source_ref"])
    assert "timestamp-semantics:reviewed" in str(row["source_ref"])


def test_open_timestamp_binding_is_supported_only_when_explicit() -> None:
    rows = ibkr_research_manifest_bar_rows(
        _batch(_bar()),
        timestamp_binding=_binding(
            role=ProviderTimestampRole.BUCKET_OPEN,
            interval_seconds=60,
            availability_lag_seconds=0,
        ),
    )
    row = rows[0]
    assert row["bucket_open_utc"] == T0.isoformat()
    assert row["bucket_close_utc"] == (
        T0 + timedelta(minutes=1)
    ).isoformat()


def test_wrong_provider_binding_fails_closed() -> None:
    with pytest.raises(ValueError, match="not canonical"):
        ibkr_research_manifest_bar_rows(
            _batch(_bar()),
            timestamp_binding=_binding(
                role=ProviderTimestampRole.BUCKET_CLOSE,
                provider_source_id="other-provider",
            ),
        )


def test_derived_availability_cannot_postdate_observed_fetch() -> None:
    fetched = T0 + timedelta(seconds=1)
    with pytest.raises(ValueError, match="after observed fetch"):
        ibkr_research_manifest_bar_rows(
            _batch(_bar(fetched_at_utc=fetched)),
            timestamp_binding=_binding(
                role=ProviderTimestampRole.BUCKET_OPEN,
                interval_seconds=60,
                availability_lag_seconds=10,
            ),
        )


def test_empty_batch_fails_closed() -> None:
    empty = IbkrHistoricalBatch(
        asset_id="nvda",
        contract_id=265598,
        symbol="NVDA",
        text="NVIDIA CORP",
        requested_period="1w",
        requested_bar="1d",
        requested_source="Last",
        outside_rth=False,
        md_availability=None,
        market_data_delay_ms=None,
        reported_points=0,
        price_factor=None,
        volume_factor=None,
        timestamp_unit="epoch_milliseconds",
        bars=(),
    )
    with pytest.raises(ValueError, match="contains no bars"):
        ibkr_research_manifest_bar_rows(
            empty,
            timestamp_binding=_binding(
                role=ProviderTimestampRole.BUCKET_CLOSE,
            ),
        )
