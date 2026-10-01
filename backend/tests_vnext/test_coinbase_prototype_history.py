from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.coinbase_prototype_history import (
    COINBASE_SOURCE_ID,
    parse_coinbase_hourly_candles,
)


UTC = timezone.utc
END = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def test_coinbase_hourly_parser_sorts_and_preserves_cross_venue_identity() -> None:
    payload = [
        [1790805600, 103.0, 108.0, 104.0, 107.0, 8.0],
        [1790802000, 99.0, 105.0, 100.0, 104.0, 12.5],
    ]
    rows = parse_coinbase_hourly_candles(
        payload,
        asset_id="btc",
        end_at_utc=END,
    )
    assert len(rows) == 2
    assert rows[0].bucket_open_utc < rows[1].bucket_open_utc
    assert rows[0].source_id == COINBASE_SOURCE_ID
    assert "coinbase-exchange" in rows[0].source_ref
    assert rows[0].interval_seconds == 3600
    assert rows[0].trade_count == 0


def test_coinbase_parser_excludes_forming_or_future_hour() -> None:
    payload = [
        [1790812800, 103.0, 108.0, 104.0, 107.0, 8.0],
    ]
    assert parse_coinbase_hourly_candles(
        payload,
        asset_id="eth",
        end_at_utc=END,
    ) == ()


def test_coinbase_parser_rejects_bad_ohlc() -> None:
    with pytest.raises(ValueError, match="geometry"):
        parse_coinbase_hourly_candles(
            [[1790802000, 101.0, 99.0, 100.0, 104.0, 12.5]],
            asset_id="btc",
            end_at_utc=END,
        )



def test_dynamic_coinbase_history_requires_explicit_product_identity() -> None:
    payload = [
        [1790802000, 99.0, 105.0, 100.0, 104.0, 12.5],
    ]
    with pytest.raises(ValueError, match="explicit Coinbase product"):
        parse_coinbase_hourly_candles(
            payload,
            asset_id="kraken:solusd",
            end_at_utc=END,
        )

    rows = parse_coinbase_hourly_candles(
        payload,
        asset_id="kraken:solusd",
        end_at_utc=END,
        coinbase_product="SOL-USD",
    )
    assert len(rows) == 1
    assert rows[0].asset_id == "kraken:solusd"
    assert "/products/SOL-USD/candles" in rows[0].source_ref
