from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from aether_vnext.ninjatrader_history import (
    NINJATRADER_HISTORY_ADAPTER_VERSION,
    NinjaTraderChartSubscription,
    cancel_chart_request,
    chart_subscription_from_response,
    get_chart_request,
    parse_historical_chart_events,
)
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID


UTC = timezone.utc


def _body(encoded: str) -> dict:
    parts = encoded.split("\n")
    assert len(parts) == 4
    return json.loads(parts[3])


def test_get_chart_request_uses_market_data_only_chart_endpoint() -> None:
    encoded = get_chart_request(
        symbol="MESZ6",
        request_id=7,
        underlying_type="MinuteBar",
        element_size=15,
        as_far_as_timestamp_utc=datetime(
            2026, 9, 27, 22, 0, tzinfo=UTC
        ),
        as_much_as_elements=66,
    )
    parts = encoded.split("\n")
    assert parts[0] == "md/getChart"
    assert parts[1] == "7"
    payload = _body(encoded)
    assert payload["symbol"] == "MESZ6"
    assert payload["chartDescription"] == {
        "underlyingType": "MinuteBar",
        "elementSize": 15,
        "elementSizeUnit": "UnderlyingUnits",
        "withHistogram": False,
    }
    assert payload["timeRange"] == {
        "asFarAsTimestamp": "2026-09-27T22:00:00.000Z",
        "asMuchAsElements": 66,
    }
    assert "order/" not in encoded
    assert "account/" not in encoded


def test_chart_request_requires_explicit_time_range_bound() -> None:
    with pytest.raises(ValueError, match="timeRange"):
        get_chart_request(
            symbol=123456,
            request_id=1,
            underlying_type="DailyBar",
            element_size=1,
        )


def test_chart_response_binds_historical_and_realtime_ids() -> None:
    subscription = chart_subscription_from_response(
        (
            {
                "s": 200,
                "i": 13,
                "d": {
                    "historicalId": 32,
                    "realtimeId": 31,
                },
            },
        ),
        request_id=13,
    )
    assert subscription == NinjaTraderChartSubscription(
        historical_id=32,
        realtime_id=31,
    )


def test_cancel_chart_uses_subscription_id_only() -> None:
    encoded = cancel_chart_request(
        subscription_id=31,
        request_id=14,
    )
    assert encoded.split("\n")[0] == "md/cancelChart"
    assert _body(encoded) == {"subscriptionId": 31}


def test_historical_chart_parser_filters_subscription_and_preserves_timestamp() -> None:
    messages = (
        {
            "e": "chart",
            "d": {
                "charts": [
                    {
                        "id": 31,
                        "td": 20170413,
                        "bars": [
                            {
                                "timestamp": "2017-04-13T10:45:00.000Z",
                                "open": 1,
                                "high": 2,
                                "low": 1,
                                "close": 2,
                                "upVolume": 1,
                                "downVolume": 1,
                            }
                        ],
                    },
                    {
                        "id": 32,
                        "td": 20170413,
                        "bars": [
                            {
                                "timestamp": "2017-04-13T11:00:00.000Z",
                                "open": 2334.25,
                                "high": 2334.5,
                                "low": 2333.0,
                                "close": 2333.75,
                                "upVolume": 4712.234,
                                "downVolume": 201.124,
                            },
                            {
                                "timestamp": "2017-04-13T11:15:00.000Z",
                                "open": 2333.75,
                                "high": 2335.0,
                                "low": 2333.5,
                                "close": 2334.75,
                                "upVolume": 100.0,
                                "downVolume": 50.0,
                            },
                        ],
                    },
                ]
            },
        },
    )
    rows = parse_historical_chart_events(
        messages,
        asset_id="mes",
        current_contract="MESZ6",
        contract_id=987654,
        historical_id=32,
        source_data_version="demo-history-v1",
        source_ref="ninjatrader:getChart:reviewed-1",
        fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
    )

    assert len(rows) == 2
    assert rows[0].provider_timestamp_utc == datetime(
        2017, 4, 13, 11, 0, tzinfo=UTC
    )
    assert rows[0].source_id == NINJATRADER_MARKET_SOURCE_ID
    assert rows[0].total_volume == pytest.approx(4913.358)
    assert NINJATRADER_HISTORY_ADAPTER_VERSION.endswith("raw_timestamp")


def test_historical_chart_parser_rejects_out_of_order_bars() -> None:
    messages = (
        {
            "e": "chart",
            "d": {
                "charts": [
                    {
                        "id": 32,
                        "bars": [
                            {
                                "timestamp": "2017-04-13T11:15:00Z",
                                "open": 10,
                                "high": 11,
                                "low": 9,
                                "close": 10,
                                "upVolume": 1,
                                "downVolume": 1,
                            },
                            {
                                "timestamp": "2017-04-13T11:00:00Z",
                                "open": 10,
                                "high": 11,
                                "low": 9,
                                "close": 10,
                                "upVolume": 1,
                                "downVolume": 1,
                            },
                        ],
                    }
                ]
            },
        },
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_historical_chart_events(
            messages,
            asset_id="mnq",
            current_contract="MNQZ6",
            contract_id=123456,
            historical_id=32,
            source_data_version="demo-history-v1",
            source_ref="reviewed-ref",
            fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
        )


def test_future_or_bad_ohlc_bar_fails_closed() -> None:
    future = (
        {
            "e": "chart",
            "d": {
                "charts": [
                    {
                        "id": 32,
                        "bars": [
                            {
                                "timestamp": "2030-01-01T00:00:00Z",
                                "open": 10,
                                "high": 11,
                                "low": 9,
                                "close": 10,
                                "upVolume": 1,
                                "downVolume": 1,
                            }
                        ],
                    }
                ]
            },
        },
    )
    with pytest.raises(ValueError, match="cannot be in the future"):
        parse_historical_chart_events(
            future,
            asset_id="mcl",
            current_contract="MCLZ6",
            contract_id=777,
            historical_id=32,
            source_data_version="v1",
            source_ref="ref",
            fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
        )
