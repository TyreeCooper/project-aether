from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.kraken_ohlcvt_history import (
    KRAKEN_OHLCVT_SOURCE_ID,
    parse_kraken_ohlcvt_csv,
    research_manifest_bar_rows,
)


UTC = timezone.utc


def test_parses_official_seven_column_shape_without_synthesizing_gaps() -> None:
    raw = "\n".join(
        (
            "1767225600,100,105,99,104,12.5,7",
            # Deliberate missing 01:00 bucket. Kraken archives omit empty intervals.
            "1767232800,104,108,103,107,8.0,4",
        )
    )
    rows = parse_kraken_ohlcvt_csv(
        raw,
        asset_id="btc",
        interval_minutes=60,
        timestamp_unit="unix_seconds",
        source_data_version="Kraken_OHLCVT_2026Q2",
        source_ref="kraken:archive:sha256:example",
    )

    assert len(rows) == 2
    assert rows[0].bucket_open_utc == datetime(
        2026, 1, 1, 0, 0, tzinfo=UTC
    )
    assert rows[0].bucket_close_utc == datetime(
        2026, 1, 1, 1, 0, tzinfo=UTC
    )
    assert rows[1].bucket_open_utc == datetime(
        2026, 1, 1, 2, 0, tzinfo=UTC
    )
    assert rows[0].available_at_utc == rows[0].bucket_close_utc
    assert rows[0].source_id == KRAKEN_OHLCVT_SOURCE_ID
    assert rows[0].trades == 7


def test_timestamp_unit_is_explicit_not_magnitude_guessed() -> None:
    raw_ms = "1767225600000,100,105,99,104,12.5,7"
    rows = parse_kraken_ohlcvt_csv(
        raw_ms,
        asset_id="eth",
        interval_minutes=60,
        timestamp_unit="unix_milliseconds",
        source_data_version="archive-v1",
        source_ref="reviewed-ref",
    )
    assert rows[0].bucket_open_utc == datetime(
        2026, 1, 1, 0, 0, tzinfo=UTC
    )

    with pytest.raises(ValueError, match="out of range"):
        parse_kraken_ohlcvt_csv(
            raw_ms,
            asset_id="eth",
            interval_minutes=60,
            timestamp_unit="unix_seconds",
            source_data_version="archive-v1",
            source_ref="reviewed-ref",
        )


def test_header_is_rejected_because_official_archive_is_headerless() -> None:
    with pytest.raises(ValueError, match="must not contain a header"):
        parse_kraken_ohlcvt_csv(
            "timestamp,open,high,low,close,volume,trades\n",
            asset_id="btc",
            interval_minutes=60,
            timestamp_unit="unix_seconds",
            source_data_version="archive-v1",
            source_ref="reviewed-ref",
        )


def test_duplicate_or_out_of_order_bucket_is_rejected() -> None:
    raw = "\n".join(
        (
            "1767225600,100,105,99,104,12.5,7",
            "1767225600,104,108,103,107,8.0,4",
        )
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_kraken_ohlcvt_csv(
            raw,
            asset_id="btc",
            interval_minutes=60,
            timestamp_unit="unix_seconds",
            source_data_version="archive-v1",
            source_ref="reviewed-ref",
        )


def test_interval_alignment_detects_wrong_or_corrupt_timestamp() -> None:
    with pytest.raises(ValueError, match="interval-aligned"):
        parse_kraken_ohlcvt_csv(
            "1767225660,100,105,99,104,12.5,7",
            asset_id="btc",
            interval_minutes=60,
            timestamp_unit="unix_seconds",
            source_data_version="archive-v1",
            source_ref="reviewed-ref",
        )


def test_bad_ohlc_geometry_and_unsupported_asset_fail_closed() -> None:
    with pytest.raises(ValueError, match="high is inconsistent"):
        parse_kraken_ohlcvt_csv(
            "1767225600,100,99,98,101,1.0,2",
            asset_id="btc",
            interval_minutes=60,
            timestamp_unit="unix_seconds",
            source_data_version="archive-v1",
            source_ref="reviewed-ref",
        )

    with pytest.raises(ValueError, match="unsupported AETHER"):
        parse_kraken_ohlcvt_csv(
            "1767225600,100,105,99,104,1.0,2",
            asset_id="sol",
            interval_minutes=60,
            timestamp_unit="unix_seconds",
            source_data_version="archive-v1",
            source_ref="reviewed-ref",
        )


def test_research_manifest_rows_preserve_source_and_closed_bar_identity() -> None:
    rows = parse_kraken_ohlcvt_csv(
        "1767225600,100,105,99,104,12.5,7",
        asset_id="btc",
        interval_minutes=15,
        timestamp_unit="unix_seconds",
        source_data_version="archive-v1",
        source_ref="reviewed-ref",
    )
    payload = research_manifest_bar_rows(rows)

    assert payload == [
        {
            "asset_id": "btc",
            "interval_seconds": 900,
            "bucket_open_utc": "2026-01-01T00:00:00+00:00",
            "bucket_close_utc": "2026-01-01T00:15:00+00:00",
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 104.0,
            "volume": 12.5,
            "source_id": KRAKEN_OHLCVT_SOURCE_ID,
            "source_data_version": "archive-v1",
            "source_ref": "reviewed-ref",
            "available_at_utc": "2026-01-01T00:15:00+00:00",
        }
    ]
