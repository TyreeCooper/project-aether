from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.ibkr_webapi_history import (
    IBKR_HISTORY_ENDPOINT,
    IBKR_HISTORY_SOURCE_ID,
    IBKR_HISTORY_TIMESTAMP_UNIT,
    IbkrHistoricalRequest,
    parse_ibkr_history_response,
)


UTC = timezone.utc


def _payload() -> dict:
    return {
        "barLength": 86400,
        "chartPanStartTime": "20250521-00:00:00",
        "data": [
            {
                "c": 212.11,
                "h": 213.94,
                "l": 210.58,
                "o": 212.09,
                "t": 1747229400000,
                "v": 100,
            },
            {
                "c": 211.34,
                "h": 212.97,
                "l": 209.53,
                "o": 211.32,
                "t": 1747315800000,
                "v": 200,
            },
        ],
        "direction": -1,
        "mdAvailability": "S",
        "mktDataDelay": 0,
        "outsideRth": False,
        "points": 2,
        "priceFactor": 100,
        "serverId": "4155828",
        "startTime": "20250513-13:30:00",
        "symbol": "NVDA",
        "text": "NVIDIA CORP",
        "timePeriod": "1w",
        "volumeFactor": 100,
    }


def test_request_binds_current_history_endpoint_query_contract() -> None:
    request = IbkrHistoricalRequest(
        contract_id=265598,
        period="1w",
        bar="1d",
        exchange="SMART",
        outside_rth=False,
        start_time_utc=datetime(2025, 5, 13, 13, 30, tzinfo=UTC),
        direction=-1,
        source="Last",
    )

    assert IBKR_HISTORY_ENDPOINT == "/v1/api/iserver/marketdata/history"
    assert request.query_params() == {
        "conid": 265598,
        "period": "1w",
        "bar": "1d",
        "outsideRth": False,
        "source": "Last",
        "exchange": "SMART",
        "startTime": "20250513-13:30:00",
        "direction": -1,
    }


def test_direction_minus_one_without_start_time_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires explicit start_time"):
        IbkrHistoricalRequest(
            contract_id=265598,
            period="1d",
            bar="1min",
            direction=-1,
        )


def test_parser_preserves_provider_timestamp_without_bucket_semantics() -> None:
    request = IbkrHistoricalRequest(
        contract_id=265598,
        period="1w",
        bar="1d",
        source="Last",
    )
    batch = parse_ibkr_history_response(
        _payload(),
        asset_id="nvda",
        request=request,
        source_data_version="ibkr-history-fetch-2026-09-27",
        source_ref="ibkr:iserver-history:reviewed-request-1",
        fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
    )

    assert batch.asset_id == "nvda"
    assert batch.contract_id == 265598
    assert batch.symbol == "NVDA"
    assert batch.timestamp_unit == IBKR_HISTORY_TIMESTAMP_UNIT
    assert batch.reported_points == 2
    assert len(batch.bars) == 2
    assert batch.bars[0].provider_timestamp_utc == datetime(
        2025, 5, 14, 13, 30, tzinfo=UTC
    )
    assert batch.bars[0].source_id == IBKR_HISTORY_SOURCE_ID
    assert batch.bars[0].open == pytest.approx(212.09)
    assert batch.bars[0].close == pytest.approx(212.11)


def test_parser_does_not_require_reported_points_to_equal_data_length() -> None:
    payload = _payload()
    payload["points"] = 1
    request = IbkrHistoricalRequest(
        contract_id=265598,
        period="1w",
        bar="1d",
    )
    batch = parse_ibkr_history_response(
        payload,
        asset_id="tsla",
        request=request,
        source_data_version="fetch-v1",
        source_ref="reviewed-ref",
        fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
    )
    assert batch.reported_points == 1
    assert len(batch.bars) == 2


def test_out_of_order_provider_timestamps_fail_closed() -> None:
    payload = _payload()
    payload["data"][1]["t"] = payload["data"][0]["t"]
    request = IbkrHistoricalRequest(
        contract_id=265598,
        period="1w",
        bar="1d",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_ibkr_history_response(
            payload,
            asset_id="pltr",
            request=request,
            source_data_version="fetch-v1",
            source_ref="reviewed-ref",
            fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
        )


def test_bad_ohlc_geometry_and_future_timestamp_fail_closed() -> None:
    request = IbkrHistoricalRequest(
        contract_id=265598,
        period="1w",
        bar="1d",
    )
    bad = _payload()
    bad["data"][0]["h"] = 200.0
    with pytest.raises(ValueError, match="high is inconsistent"):
        parse_ibkr_history_response(
            bad,
            asset_id="nvda",
            request=request,
            source_data_version="fetch-v1",
            source_ref="reviewed-ref",
            fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
        )

    future = _payload()
    future["data"] = [{
        "o": 100.0,
        "h": 101.0,
        "l": 99.0,
        "c": 100.5,
        "v": 1,
        "t": 1893456000000,
    }]
    with pytest.raises(ValueError, match="cannot be in the future"):
        parse_ibkr_history_response(
            future,
            asset_id="nvda",
            request=request,
            source_data_version="fetch-v1",
            source_ref="reviewed-ref",
            fetched_at_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
        )
