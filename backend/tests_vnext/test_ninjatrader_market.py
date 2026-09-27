from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from aether_vnext.ninjatrader_market import (
    NINJATRADER_HEARTBEAT_REPLY,
    authorize_market_data_request,
    decode_server_frame,
    encode_request,
    parse_quote_events,
    require_success_response,
    subscribe_quote_request,
    unsubscribe_quote_request,
)


UTC = timezone.utc


def test_request_encoder_preserves_documented_four_field_protocol() -> None:
    assert encode_request(
        endpoint="md/subscribeQuote",
        request_id=2,
        body={"symbol": "MESZ6"},
    ) == 'md/subscribeQuote\n2\n\n{"symbol":"MESZ6"}'


def test_authorize_request_uses_token_as_body_and_no_trade_endpoint() -> None:
    encoded = authorize_market_data_request(
        md_access_token="md-token-test",
        request_id=1,
    )
    assert encoded == "authorize\n1\n\nmd-token-test"
    assert "order/" not in encoded
    assert "account/" not in encoded


def test_quote_subscription_and_unsubscribe_are_market_data_only() -> None:
    subscribe = subscribe_quote_request(symbol="MESZ6", request_id=2)
    unsubscribe = unsubscribe_quote_request(symbol=123456, request_id=3)

    assert subscribe == 'md/subscribeQuote\n2\n\n{"symbol":"MESZ6"}'
    assert unsubscribe == 'md/unsubscribeQuote\n3\n\n{"symbol":123456}'


def test_decode_open_heartbeat_array_and_close_frames() -> None:
    assert decode_server_frame("o").frame_type == "o"
    heartbeat = decode_server_frame("h")
    assert heartbeat.frame_type == "h"
    assert NINJATRADER_HEARTBEAT_REPLY == "[]"

    array = decode_server_frame(
        'a[{"s":200,"i":1},{"e":"md","d":{"quotes":[]}}]'
    )
    assert array.frame_type == "a"
    assert len(array.messages) == 2

    close = decode_server_frame('c[3000,"Go away!"]')
    assert close.frame_type == "c"
    assert close.close_payload == [3000, "Go away!"]


def test_success_response_is_correlated_by_request_id() -> None:
    frame = decode_server_frame(
        'a[{"s":200,"i":1},{"s":200,"i":2,"d":{"ok":true}}]'
    )
    response = require_success_response(
        frame.messages,
        request_id=2,
        operation="md/subscribeQuote",
    )
    assert response["d"] == {"ok": True}


def test_non_success_response_fails_closed() -> None:
    frame = decode_server_frame(
        'a[{"s":403,"i":2,"d":"not entitled"}]'
    )
    with pytest.raises(RuntimeError, match="status 403"):
        require_success_response(
            frame.messages,
            request_id=2,
            operation="md/subscribeQuote",
        )


def test_quote_event_parser_preserves_contract_id_and_level_one_prices() -> None:
    payload = [
        {
            "e": "md",
            "d": {
                "quotes": [
                    {
                        "timestamp": "2026-09-27T03:05:06.588Z",
                        "contractId": 123456,
                        "entries": {
                            "Bid": {"price": 6700.25, "size": 12},
                            "Offer": {"price": 6700.50, "size": 8},
                            "Trade": {"price": 6700.25, "size": 3},
                            "TotalTradeVolume": {"size": 841200},
                        },
                    }
                ]
            },
        }
    ]

    events = parse_quote_events(tuple(payload))
    assert len(events) == 1
    event = events[0]
    assert event.contract_id == 123456
    assert event.timestamp_utc == datetime(
        2026, 9, 27, 3, 5, 6, 588000, tzinfo=UTC
    )
    assert event.bid == 6700.25
    assert event.ask == 6700.50
    assert event.last == 6700.25


def test_partial_quote_update_is_retained_without_fabricating_missing_prices() -> None:
    events = parse_quote_events(
        (
            {
                "e": "md",
                "d": {
                    "quotes": [
                        {
                            "timestamp": "2026-09-27T03:05:06.588Z",
                            "contractId": 42,
                            "entries": {"Bid": {"price": 100.0}},
                        }
                    ]
                },
            },
        )
    )
    assert len(events) == 1
    assert events[0].bid == 100.0
    assert events[0].ask is None
    assert events[0].last is None


def test_malformed_market_event_does_not_create_quote_evidence() -> None:
    events = parse_quote_events(
        (
            {"e": "md", "d": {"quotes": [{"contractId": "bad"}]}},
            {"e": "props", "d": {}},
        )
    )
    assert events == ()


def test_request_inputs_reject_newline_injection() -> None:
    with pytest.raises(ValueError):
        authorize_market_data_request(md_access_token="token\nother")
    with pytest.raises(ValueError):
        subscribe_quote_request(symbol="MESZ6\norder/placeorder", request_id=2)
