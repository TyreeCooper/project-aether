from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.prototype_history_sources import (
    CRYPTOCOMPARE_SOURCE_ID,
    KRAKEN_DAILY_SOURCE_ID,
    parse_cryptocompare_kraken_hourly_payload,
    parse_kraken_completed_daily_payload,
)


UTC = timezone.utc
END = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)


def test_cryptocompare_parser_keeps_exchange_scoped_hourly_provenance() -> None:
    payload = {
        "Response": "Success",
        "Data": {
            "Data": [
                {
                    "time": 1790802000,
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 104.0,
                    "volumefrom": 12.5,
                    "volumeto": 1300.0,
                },
                {
                    "time": 1790805600,
                    "open": 104.0,
                    "high": 108.0,
                    "low": 103.0,
                    "close": 107.0,
                    "volumefrom": 8.0,
                    "volumeto": 850.0,
                },
            ]
        },
    }
    rows = parse_cryptocompare_kraken_hourly_payload(
        payload,
        asset_id="btc",
        end_at_utc=END,
    )
    assert len(rows) == 2
    assert all(row.source_id == CRYPTOCOMPARE_SOURCE_ID for row in rows)
    assert all("e=Kraken" in row.source_ref for row in rows)
    assert all("tryConversion=false" in row.source_ref for row in rows)
    assert rows[0].interval_seconds == 3600
    assert rows[0].trade_count == 0


def test_cryptocompare_zero_placeholder_is_absent_not_synthetic_bar() -> None:
    payload = {
        "Response": "Success",
        "Data": {
            "Data": [
                {
                    "time": 1790802000,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "close": 0,
                    "volumefrom": 0,
                }
            ]
        },
    }
    assert parse_cryptocompare_kraken_hourly_payload(
        payload,
        asset_id="eth",
        end_at_utc=END,
    ) == ()


def test_cryptocompare_provider_error_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="rate limit"):
        parse_cryptocompare_kraken_hourly_payload(
            {"Response": "Error", "Message": "rate limit"},
            asset_id="btc",
            end_at_utc=END,
        )


def test_kraken_daily_parser_drops_forming_final_row() -> None:
    payload = {
        "error": [],
        "result": {
            "BTC/USD": [
                [1790630400, "100", "105", "99", "104", "102", "12.5", 7],
                [1790716800, "104", "108", "103", "107", "106", "8.0", 4],
                # Kraken documents the final row as the current forming interval.
                [1790803200, "107", "109", "106", "108", "108", "3.0", 2],
            ],
            "last": 1790803200,
        },
    }
    rows = parse_kraken_completed_daily_payload(
        payload,
        asset_id="btc",
        end_at_utc=END,
    )
    assert len(rows) == 2
    assert all(row.source_id == KRAKEN_DAILY_SOURCE_ID for row in rows)
    assert rows[-1].close == 107.0
    assert rows[-1].trade_count == 4


def test_kraken_daily_error_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="Kraken OHLC error"):
        parse_kraken_completed_daily_payload(
            {"error": ["EGeneral:Unavailable"], "result": {}},
            asset_id="btc",
            end_at_utc=END,
        )
