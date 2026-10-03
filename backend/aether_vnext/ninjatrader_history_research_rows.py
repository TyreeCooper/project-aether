"""Normalize reviewed NinjaTrader historical bars into research-manifest rows.

No NinjaTrader/Tradovate timestamp semantics are assumed here. Callers must supply
an explicit HistoricalTimestampBinding whose provider_source_id matches the parsed
market-data source.

Futures contract identity is preserved in source lineage because the research-bar
warehouse is asset-centric while execution truth remains contract-specific.

This module performs no network I/O and does not persist research data.
"""
from __future__ import annotations

from aether_vnext.historical_time_binding import (
    HistoricalTimestampBinding,
    normalize_historical_provider_time,
)
from aether_vnext.ninjatrader_history import NinjaTraderHistoricalBar
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID


def _normalized_source_ref(
    *,
    bar: NinjaTraderHistoricalBar,
    binding: HistoricalTimestampBinding,
) -> str:
    trade_date = (
        ""
        if bar.trade_date is None
        else f"|trade_date={bar.trade_date}"
    )
    return (
        f"{bar.source_ref}"
        f"|contract={bar.current_contract}"
        f"|contract_id={bar.contract_id}"
        f"{trade_date}"
        f"|timestamp_binding={binding.binding_id}"
        f"|timestamp_review={binding.reviewed_source_ref}"
    )


def ninjatrader_research_manifest_bar_rows(
    bars: tuple[NinjaTraderHistoricalBar, ...],
    *,
    timestamp_binding: HistoricalTimestampBinding,
) -> list[dict[str, object]]:
    """Convert parsed NinjaTrader history into reviewed PIT research rows."""
    if not bars:
        raise ValueError("NinjaTrader historical input contains no bars")
    if (
        timestamp_binding.provider_source_id
        != NINJATRADER_MARKET_SOURCE_ID
    ):
        raise ValueError(
            "NinjaTrader timestamp binding provider_source_id is not canonical"
        )

    out: list[dict[str, object]] = []
    for bar in bars:
        normalized = normalize_historical_provider_time(
            provider_timestamp_utc=bar.provider_timestamp_utc,
            provider_source_id=bar.source_id,
            binding=timestamp_binding,
        )
        if normalized.available_at_utc > bar.fetched_at_utc:
            raise ValueError(
                "reviewed NinjaTrader availability time occurs after observed fetch"
            )

        out.append(
            {
                "asset_id": bar.asset_id,
                "interval_seconds": timestamp_binding.interval_seconds,
                "bucket_open_utc": normalized.bucket_open_utc.isoformat(),
                "bucket_close_utc": normalized.bucket_close_utc.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.total_volume,
                "source_id": bar.source_id,
                "source_data_version": bar.source_data_version,
                "source_ref": _normalized_source_ref(
                    bar=bar,
                    binding=timestamp_binding,
                ),
                "available_at_utc": normalized.available_at_utc.isoformat(),
            }
        )
    return out
