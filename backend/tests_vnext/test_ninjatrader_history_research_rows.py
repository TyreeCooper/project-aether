from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.historical_time_binding import (
    HistoricalTimestampBinding,
    ProviderTimestampRole,
)
from aether_vnext.ninjatrader_history import NinjaTraderHistoricalBar
from aether_vnext.ninjatrader_history_research_rows import (
    ninjatrader_research_manifest_bar_rows,
)
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID


UTC = timezone.utc
T0 = datetime(2025, 5, 14, 13, 30, tzinfo=UTC)


def _bar(
    *,
    provider_timestamp_utc: datetime = T0,
    fetched_at_utc: datetime | None = None,
    trade_date: int | None = 20250514,
) -> NinjaTraderHistoricalBar:
    return NinjaTraderHistoricalBar(
        asset_id="mes",
        current_contract="MESM5",
        contract_id=987654,
        historical_id=42,
        provider_timestamp_utc=provider_timestamp_utc,
        trade_date=trade_date,
        open=5900.0,
        high=5905.0,
        low=5895.0,
        close=5902.0,
        up_volume=120.0,
        down_volume=80.0,
        source_id=NINJATRADER_MARKET_SOURCE_ID,
        source_data_version="nt-history-fetch-v1",
        source_ref="ninjatrader:reviewed-chart:1",
        fetched_at_utc=(
            fetched_at_utc
            if fetched_at_utc is not None
            else T0 + timedelta(days=5)
        ),
    )


def _binding(
    *,
    role: ProviderTimestampRole,
    interval_seconds: int = 900,
    availability_lag_seconds: int = 1,
    provider_source_id: str = NINJATRADER_MARKET_SOURCE_ID,
) -> HistoricalTimestampBinding:
    return HistoricalTimestampBinding(
        binding_id="ninjatrader-reviewed-time-v1",
        provider_source_id=provider_source_id,
        interval_seconds=interval_seconds,
        timestamp_role=role,
        availability_lag_seconds=availability_lag_seconds,
        reviewed_source_ref="ninjatrader-doc:timestamp-semantics:reviewed",
    )


def test_close_timestamp_binding_creates_futures_research_row() -> None:
    rows = ninjatrader_research_manifest_bar_rows(
        (_bar(),),
        timestamp_binding=_binding(
            role=ProviderTimestampRole.BUCKET_CLOSE,
        ),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["asset_id"] == "mes"
    assert row["interval_seconds"] == 900
    assert row["bucket_close_utc"] == T0.isoformat()
    assert row["bucket_open_utc"] == (
        T0 - timedelta(minutes=15)
    ).isoformat()
    assert row["available_at_utc"] == (
        T0 + timedelta(seconds=1)
    ).isoformat()
    assert row["volume"] == pytest.approx(200.0)
    assert "contract=MESM5" in str(row["source_ref"])
    assert "contract_id=987654" in str(row["source_ref"])
    assert "trade_date=20250514" in str(row["source_ref"])
    assert "ninjatrader-reviewed-time-v1" in str(row["source_ref"])


def test_open_timestamp_binding_is_supported_only_when_explicit() -> None:
    rows = ninjatrader_research_manifest_bar_rows(
        (_bar(trade_date=None),),
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
    assert "trade_date=" not in str(row["source_ref"])


def test_wrong_provider_binding_fails_closed() -> None:
    with pytest.raises(ValueError, match="not canonical"):
        ninjatrader_research_manifest_bar_rows(
            (_bar(),),
            timestamp_binding=_binding(
                role=ProviderTimestampRole.BUCKET_CLOSE,
                provider_source_id="other-provider",
            ),
        )


def test_derived_availability_cannot_postdate_observed_fetch() -> None:
    fetched = T0 + timedelta(seconds=1)
    with pytest.raises(ValueError, match="after observed fetch"):
        ninjatrader_research_manifest_bar_rows(
            (_bar(fetched_at_utc=fetched),),
            timestamp_binding=_binding(
                role=ProviderTimestampRole.BUCKET_OPEN,
                interval_seconds=60,
                availability_lag_seconds=10,
            ),
        )


def test_empty_input_fails_closed() -> None:
    with pytest.raises(ValueError, match="contains no bars"):
        ninjatrader_research_manifest_bar_rows(
            (),
            timestamp_binding=_binding(
                role=ProviderTimestampRole.BUCKET_CLOSE,
            ),
        )
