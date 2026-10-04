from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlparse

import pytest

from aether_vnext.ibkr_webapi_market import (
    IBKR_CPGW_WEBSOCKET_URL,
    IBKR_MARKET_DATA_FIELDS,
    IBKR_MARKET_PRINT_FIELDS,
    IBKR_SHORTABILITY_FIELDS,
    IBKR_WEBAPI_MARKET_PRINT_ADAPTER_VERSION,
    IBKR_WEBAPI_MARKET_SOURCE_ID,
    IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
    fetch_ibkr_shortability,
    fetch_ibkr_trade_prints,
    fetch_ibkr_top_of_book,
    market_data_subscription,
    parse_ibkr_trade_print,
)


UTC = timezone.utc


class FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = [json.dumps(row) for row in messages]
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if not self.messages:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")
        return self.messages.pop(0)


def _connect(messages: list[dict]):
    socket = FakeWebSocket(messages)
    calls = []

    def factory(url: str, **kwargs):
        calls.append((url, kwargs))
        return socket

    return socket, calls, factory


def _realtime(
    *,
    conid: int,
    bid: object | None = None,
    ask: object | None = None,
    last: object | None = None,
    updated: int = 1_796_000_000_000,
    availability: str = "RpB",
) -> dict:
    row: dict[str, object] = {
        "conid": conid,
        "6509": availability,
        "_updated": updated,
    }
    if bid is not None:
        row["84"] = bid
    if ask is not None:
        row["86"] = ask
    if last is not None:
        row["31"] = last
    return row


def test_market_data_subscription_is_smd_only_and_requests_required_fields() -> None:
    encoded = market_data_subscription(contract_id=265598)
    assert encoded == (
        'smd+265598+{"fields":["31","84","86","6509"]}'
    )
    assert tuple(IBKR_MARKET_DATA_FIELDS) == ("31", "84", "86", "6509")
    assert "order" not in encoded.lower()
    assert "account" not in encoded.lower()


@pytest.mark.asyncio
async def test_cookie_auth_collects_incremental_realtime_top_of_book() -> None:
    socket, calls, factory = _connect(
        [
            _realtime(conid=265598, bid="100.25"),
            _realtime(
                conid=265598,
                ask="100.35",
                last="100.30",
                updated=1_796_000_000_125,
            ),
        ]
    )

    batch = await fetch_ibkr_top_of_book(
        asset_contract_ids={"nvda": 265598},
        session_token="session-cookie-token",
        timeout_s=1.0,
        connect_factory=factory,
    )

    assert calls[0][0] == IBKR_CPGW_WEBSOCKET_URL
    assert calls[0][1]["additional_headers"] == {
        "Cookie": "api=session-cookie-token"
    }
    assert socket.sent == [
        'smd+265598+{"fields":["31","84","86","6509"]}'
    ]
    assert batch.auth_mode == "cpgw_cookie"
    assert batch.requested_contract_ids == (265598,)
    assert len(batch.quotes) == 1
    quote = batch.quotes[0]
    assert quote.asset_id == "nvda"
    assert quote.venue == "IBKR"
    assert quote.source_id == IBKR_WEBAPI_MARKET_SOURCE_ID
    assert quote.bid == 100.25
    assert quote.ask == 100.35
    assert quote.last == 100.30
    assert quote.mark == pytest.approx(100.30)
    assert quote.exchange_ts == datetime.fromtimestamp(
        1_796_000_000.125,
        tz=UTC,
    )


@pytest.mark.asyncio
async def test_oauth_query_auth_never_returns_session_token_in_batch_metadata() -> None:
    _, calls, factory = _connect(
        [
            _realtime(
                conid=265598,
                bid="100",
                ask="101",
                last="100.5",
            )
        ]
    )
    url = "wss://api.ibkr.example.test/v1/api/ws?existing=1"

    batch = await fetch_ibkr_top_of_book(
        asset_contract_ids={"nvda": 265598},
        session_token="sensitive-token",
        auth_mode="oauth2_query",
        websocket_url=url,
        timeout_s=1.0,
        connect_factory=factory,
    )

    parsed = urlparse(calls[0][0])
    query = parse_qs(parsed.query)
    assert query["sessionToken"] == ["sensitive-token"]
    assert query["existing"] == ["1"]
    assert "additional_headers" not in calls[0][1]
    assert batch.websocket_url == url
    assert "sensitive-token" not in batch.websocket_url


@pytest.mark.asyncio
async def test_delayed_or_frozen_market_data_fails_closed() -> None:
    for availability in ("DpB", "ZpB", "YpB", "NpB"):
        _, _, factory = _connect(
            [
                _realtime(
                    conid=265598,
                    bid="100",
                    ask="101",
                    availability=availability,
                )
            ]
        )
        with pytest.raises(
            RuntimeError,
            match="ibkr_market_data_not_realtime",
        ):
            await fetch_ibkr_top_of_book(
                asset_contract_ids={"nvda": 265598},
                session_token="token",
                timeout_s=1.0,
                connect_factory=factory,
            )


@pytest.mark.asyncio
async def test_halted_last_price_fails_closed() -> None:
    _, _, factory = _connect(
        [
            _realtime(
                conid=265598,
                bid="100",
                ask="101",
                last="H100.5",
            )
        ]
    )
    with pytest.raises(RuntimeError, match="ibkr_market_halted"):
        await fetch_ibkr_top_of_book(
            asset_contract_ids={"nvda": 265598},
            session_token="token",
            timeout_s=1.0,
            connect_factory=factory,
        )


@pytest.mark.asyncio
async def test_unknown_contract_messages_do_not_satisfy_requested_contract() -> None:
    _, _, factory = _connect(
        [
            _realtime(
                conid=999999,
                bid="100",
                ask="101",
            )
        ]
    )
    with pytest.raises(TimeoutError, match="265598"):
        await fetch_ibkr_top_of_book(
            asset_contract_ids={"nvda": 265598},
            session_token="token",
            timeout_s=0.01,
            connect_factory=factory,
        )


@pytest.mark.asyncio
async def test_insecure_tls_override_is_localhost_only() -> None:
    called = False

    def factory(url: str, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    with pytest.raises(ValueError, match="localhost"):
        await fetch_ibkr_top_of_book(
            asset_contract_ids={"nvda": 265598},
            session_token="token",
            websocket_url="wss://api.ibkr.example.test/v1/api/ws",
            allow_insecure_localhost_tls=True,
            connect_factory=factory,
        )

    assert called is False


def test_contract_ids_must_be_unique_positive_integers() -> None:
    with pytest.raises(ValueError, match="positive"):
        # Validation occurs before the network factory is used.
        asyncio.run(
            fetch_ibkr_top_of_book(
                asset_contract_ids={"nvda": 0},
                session_token="token",
                connect_factory=lambda *args, **kwargs: None,
            )
        )

    with pytest.raises(ValueError, match="duplicate IBKR contract ID"):
        asyncio.run(
            fetch_ibkr_top_of_book(
                asset_contract_ids={"nvda": 265598, "tsla": 265598},
                session_token="token",
                connect_factory=lambda *args, **kwargs: None,
            )
        )


def test_shortability_subscription_fields_are_exact_documented_tags() -> None:
    assert IBKR_SHORTABILITY_FIELDS == ("7636", "7637", "7644", "6509")
    encoded = market_data_subscription(
        contract_id=265598,
        fields=IBKR_SHORTABILITY_FIELDS,
    )
    assert encoded == (
        'smd+265598+{"fields":["7636","7637","7644","6509"]}'
    )


@pytest.mark.asyncio
async def test_shortability_stream_builds_realtime_provider_evidence() -> None:
    socket, calls, factory = _connect(
        [
            {
                "conid": 265598,
                "6509": "RpB",
                "7636": "12,500",
                "_updated": 1_796_000_000_125,
            },
            {
                "conid": 265598,
                "7637": "0.42",
                "7644": "Shortable",
            },
        ]
    )

    batch = await fetch_ibkr_shortability(
        asset_contract_ids={"nvda": 265598},
        session_token="session-cookie-token",
        timeout_s=1.0,
        connect_factory=factory,
    )

    assert calls[0][1]["additional_headers"] == {
        "Cookie": "api=session-cookie-token"
    }
    assert socket.sent == [
        'smd+265598+{"fields":["7636","7637","7644","6509"]}'
    ]
    assert len(batch.evidence) == 1
    evidence = batch.evidence[0]
    assert evidence.asset_id == "nvda"
    assert evidence.provider_id == IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID
    assert evidence.market_data_contract_id == 265598
    assert evidence.shortable_shares == 12_500
    assert evidence.market_data_availability == "RpB"
    assert evidence.provider_updated_at_utc == datetime.fromtimestamp(
        1_796_000_000.125,
        tz=UTC,
    )


@pytest.mark.asyncio
async def test_shortability_delayed_or_frozen_data_fails_closed() -> None:
    for availability in ("DpB", "ZpB", "YpB", "NpB"):
        _, _, factory = _connect(
            [
                {
                    "conid": 265598,
                    "6509": availability,
                    "7636": "1000",
                }
            ]
        )
        with pytest.raises(
            RuntimeError,
            match="ibkr_shortability_not_realtime",
        ):
            await fetch_ibkr_shortability(
                asset_contract_ids={"nvda": 265598},
                session_token="token",
                timeout_s=1.0,
                connect_factory=factory,
            )


@pytest.mark.asyncio
async def test_shortability_zero_shares_is_valid_unavailable_evidence() -> None:
    _, _, factory = _connect(
        [
            {
                "conid": 265598,
                "6509": "RpB",
                "7636": "0",
                "7637": "0.00",
                "7644": "Not shortable",
                "_updated": 1_796_000_000_125,
            }
        ]
    )
    batch = await fetch_ibkr_shortability(
        asset_contract_ids={"nvda": 265598},
        session_token="token",
        timeout_s=1.0,
        connect_factory=factory,
    )
    assert batch.evidence[0].shortable_shares == 0


def test_trade_print_fields_are_exact_documented_tags() -> None:
    assert IBKR_MARKET_PRINT_FIELDS == ("31", "7059", "6509")
    encoded = market_data_subscription(
        contract_id=265598,
        fields=IBKR_MARKET_PRINT_FIELDS,
    )
    assert encoded == 'smd+265598+{"fields":["31","7059","6509"]}'


def test_trade_print_parser_requires_same_message_price_size_and_realtime() -> None:
    received = datetime(2026, 9, 29, 20, 0, tzinfo=UTC)
    payload = {
        "conid": 265598,
        "31": "100.50",
        "7059": "7",
        "6509": "RpB",
        "_updated": 1_796_000_000_125,
    }
    print_ = parse_ibkr_trade_print(
        payload,
        asset_id="nvda",
        received_at_utc=received,
    )
    assert print_ is not None
    assert print_.asset_id == "nvda"
    assert print_.price == 100.50
    assert print_.volume == 7
    assert print_.source_id == IBKR_WEBAPI_MARKET_SOURCE_ID
    assert print_.exchange_ts == datetime.fromtimestamp(
        1_796_000_000.125,
        tz=UTC,
    )

    assert parse_ibkr_trade_print(
        {**payload, "7059": None},
        asset_id="nvda",
        received_at_utc=received,
    ) is None
    assert parse_ibkr_trade_print(
        {key: value for key, value in payload.items() if key != "7059"},
        asset_id="nvda",
        received_at_utc=received,
    ) is None

    with pytest.raises(RuntimeError, match="ibkr_market_print_not_realtime"):
        parse_ibkr_trade_print(
            {**payload, "6509": "DpB"},
            asset_id="nvda",
            received_at_utc=received,
        )


@pytest.mark.asyncio
async def test_trade_print_stream_collects_provider_last_price_and_size() -> None:
    socket, calls, factory = _connect(
        [
            {
                "conid": 265598,
                "31": "100.50",
                "7059": "7",
                "6509": "RpB",
                "_updated": 1_796_000_000_125,
            }
        ]
    )

    batch = await fetch_ibkr_trade_prints(
        asset_contract_ids={"nvda": 265598},
        session_token="session-cookie-token",
        timeout_s=1.0,
        connect_factory=factory,
    )

    assert calls[0][1]["additional_headers"] == {
        "Cookie": "api=session-cookie-token"
    }
    assert socket.sent == [
        'smd+265598+{"fields":["31","7059","6509"]}'
    ]
    assert batch.requested_contract_ids == (265598,)
    assert len(batch.prints) == 1
    assert batch.prints[0].price == 100.50
    assert batch.prints[0].volume == 7
    assert IBKR_WEBAPI_MARKET_PRINT_ADAPTER_VERSION.endswith("last_size_v1")
