"""Normalize reviewed IBKR historical bars into research-manifest rows.

No IBKR timestamp semantics are assumed here. Callers must supply an explicit
HistoricalTimestampBinding whose provider_source_id matches the parsed IBKR source.

This module performs no network I/O and does not persist research data.
"""
from __future__ import annotations

from aether_vnext.historical_time_binding import (
    HistoricalTimestampBinding,
    normalize_historical_provider_time,
)
from aether_vnext.ibkr_webapi_history import (
    IBKR_HISTORY_SOURCE_ID,
    IbkrHistoricalBatch,
)


def _normalized_source_ref(
    *,
    raw_source_ref: str,
    binding: HistoricalTimestampBinding,
) -> str:
    return (
        f"{raw_source_ref}"
        f"|timestamp_binding={binding.binding_id}"
        f"|timestamp_review={binding.reviewed_source_ref}"
    )


def ibkr_research_manifest_bar_rows(
    batch: IbkrHistoricalBatch,
    *,
    timestamp_binding: HistoricalTimestampBinding,
) -> list[dict[str, object]]:
    """Convert one parsed IBKR history batch into reviewed PIT bar rows."""
    if not batch.bars:
        raise ValueError("IBKR historical batch contains no bars")
    if timestamp_binding.provider_source_id != IBKR_HISTORY_SOURCE_ID:
        raise ValueError(
            "IBKR timestamp binding provider_source_id is not canonical"
        )

    out: list[dict[str, object]] = []
    for bar in batch.bars:
        normalized = normalize_historical_provider_time(
            provider_timestamp_utc=bar.provider_timestamp_utc,
            provider_source_id=bar.source_id,
            binding=timestamp_binding,
        )
        if normalized.available_at_utc > bar.fetched_at_utc:
            raise ValueError(
                "reviewed IBKR availability time occurs after observed fetch"
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
                "volume": bar.volume,
                "source_id": bar.source_id,
                "source_data_version": bar.source_data_version,
                "source_ref": _normalized_source_ref(
                    raw_source_ref=bar.source_ref,
                    binding=timestamp_binding,
                ),
                "available_at_utc": normalized.available_at_utc.isoformat(),
            }
        )
    return out
