from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from aether_vnext.ninjatrader_demo import (
    NinjaTraderDemoMarketAuth,
    fetch_ninjatrader_demo_quote,
)
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID
from aether_vnext.registry_runtime import RuntimeRegistryBinding


UTC = timezone.utc
FUTURE = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)


class FakeWebSocket:
    def __init__(self, frames: list[str]) -> None:
        self.frames = list(frames)
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if not self.frames:
            raise RuntimeError("fake socket exhausted")
        return self.frames.pop(0)


def _auth(**overrides) -> NinjaTraderDemoMarketAuth:
    values = {
        "md_access_token": "demo-md-token",
        "md_demo_host": "tenant-md-demo.example.test",
        "expiration_time_utc": FUTURE,
    }
    values.update(overrides)
    return NinjaTraderDemoMarketAuth(**values)


def _binding(**overrides) -> RuntimeRegistryBinding:
    values = {
        "asset_id": "mes",
        "broker_symbol": "MESZ6",
        "primary_market_source_id": NINJATRADER_MARKET_SOURCE_ID,
        "stale_threshold_ms": 1500,
        "calendar_provider_id": "reviewed.calendar",
        "current_contract": "MESZ6",
        "market_data_contract_id": 987654,
        "expiry_utc": FUTURE,
        "next_contract": "MESH7",
        "source_ref": "reviewed-demo-binding",
    }
    values.update(overrides)
    return RuntimeRegistryBinding(**values)


def _connect(frames: list[str]):
    socket = FakeWebSocket(frames)
    calls = []

    def factory(url: str, **kwargs):
        calls.append((url, kwargs))
        return socket

    return socket, calls, factory


def test_market_only_auth_payload_rejects_trading_or_live_material() -> None:
    with pytest.raises(ValueError, match="prohibited"):
        NinjaTraderDemoMarketAuth.from_market_only_payload(
            {
                "mdAccessToken": "md-token",
                "accessToken": "trade-token",
                "apiHosts": {"mdDemo": "demo.example.test"},
            }
        )

    with pytest.raises(ValueError, match="mdDemo only"):
        NinjaTraderDemoMarketAuth.from_market_only_payload(
            {
                "mdAccessToken": "md-token",
                "apiHosts": {
                    "mdDemo": "demo.example.test",
                    "mdLive": "live.example.test",
                },
            }
        )


def test_market_only_auth_uses_authoritative_demo_host() -> None:
    auth = NinjaTraderDemoMarketAuth.from_market_only_payload(
        {
            "mdAccessToken": "md-token",
            "apiHosts": {"mdDemo": "org-md-demo.example.test"},
            "expirationTime": "2027-03-01T12:00:00Z",
        }
    )
    assert auth.websocket_url == (
        "wss://org-md-demo.example.test/v1/websocket"
    )
    assert auth.md_access_token == "md-token"
    assert auth.expiration_time_utc == FUTURE


def test_demo_host_refuses_scheme_path_port_or_live_material() -> None:
    for host in (
        "wss://md-demo.example.test",
        "md-demo.example.test/v1/websocket",
        "md-demo.example.test:443",
    ):
        with pytest.raises(ValueError, match="bare hostname"):
            _auth(md_demo_host=host)


@pytest.mark.asyncio
async def test_demo_transport_authorizes_subscribes_heartbeats_and_maps_contract_id() -> None:
    quote_message = {
        "e": "md",
        "d": {
            "quotes": [
                {
                    "timestamp": "2026-09-27T03:12:00.125Z",
                    "contractId": 987654,
                    "entries": {
                        "Bid": {"price": 6700.25, "size": 10},
                        "Offer": {"price": 6700.50, "size": 8},
                        "Trade": {"price": 6700.25, "size": 2},
                    },
                }
            ]
        },
    }
    socket, calls, factory = _connect(
        [
            "o",
            'a[{"s":200,"i":1}]',
            "h",
            'a[{"s":200,"i":2}]',
            "a" + json.dumps([quote_message], separators=(",", ":")),
        ]
    )

    sample = await fetch_ninjatrader_demo_quote(
        binding=_binding(),
        auth=_auth(),
        timeout_s=1.0,
        require_trade_print=True,
        connect_factory=factory,
    )

    assert calls[0][0] == (
        "wss://tenant-md-demo.example.test/v1/websocket"
    )
    assert sample.asset_id == "mes"
    assert sample.current_contract == "MESZ6"
    assert sample.contract_id == 987654
    assert sample.heartbeat_count == 1
    assert sample.quote.source_id == NINJATRADER_MARKET_SOURCE_ID
    assert sample.quote.bid == 6700.25
    assert sample.quote.ask == 6700.50
    assert sample.quote.last == 6700.25
    assert sample.quote.mark == 6700.375
    assert sample.quote.exchange_ts == datetime(
        2026, 9, 27, 3, 12, 0, 125000, tzinfo=UTC
    )
    assert sample.trade_print is not None
    assert sample.trade_print.price == 6700.25
    assert sample.trade_print.volume == 2
    assert sample.trade_print.exchange_ts == sample.quote.exchange_ts

    assert socket.sent[0] == "authorize\n1\n\ndemo-md-token"
    assert socket.sent[1] == 'md/subscribeQuote\n2\n\n{"symbol":"MESZ6"}'
    assert socket.sent[2] == "[]"


@pytest.mark.asyncio
async def test_partial_updates_accumulate_without_fabricating_prices() -> None:
    bid_only = {
        "e": "md",
        "d": {
            "quotes": [
                {
                    "timestamp": "2026-09-27T03:12:00.100Z",
                    "contractId": 987654,
                    "entries": {"Bid": {"price": 6700.25}},
                }
            ]
        },
    }
    ask_only = {
        "e": "md",
        "d": {
            "quotes": [
                {
                    "timestamp": "2026-09-27T03:12:00.200Z",
                    "contractId": 987654,
                    "entries": {"Offer": {"price": 6700.50}},
                }
            ]
        },
    }
    socket, _, factory = _connect(
        [
            "o",
            'a[{"s":200,"i":1}]',
            'a[{"s":200,"i":2}]',
            "a" + json.dumps([bid_only], separators=(",", ":")),
            "a" + json.dumps([ask_only], separators=(",", ":")),
        ]
    )

    sample = await fetch_ninjatrader_demo_quote(
        binding=_binding(),
        auth=_auth(),
        timeout_s=1.0,
        connect_factory=factory,
    )

    assert sample.quote.bid == 6700.25
    assert sample.quote.ask == 6700.50
    assert sample.quote.last is None


@pytest.mark.asyncio
async def test_unexpected_contract_id_fails_closed() -> None:
    wrong = {
        "e": "md",
        "d": {
            "quotes": [
                {
                    "timestamp": "2026-09-27T03:12:00.100Z",
                    "contractId": 111111,
                    "entries": {
                        "Bid": {"price": 6700.25},
                        "Offer": {"price": 6700.50},
                    },
                }
            ]
        },
    }
    _, _, factory = _connect(
        [
            "o",
            'a[{"s":200,"i":1}]',
            'a[{"s":200,"i":2}]',
            "a" + json.dumps([wrong], separators=(",", ":")),
        ]
    )

    with pytest.raises(RuntimeError, match="contractId"):
        await fetch_ninjatrader_demo_quote(
            binding=_binding(),
            auth=_auth(),
            timeout_s=1.0,
            connect_factory=factory,
        )


@pytest.mark.asyncio
async def test_expired_market_token_fails_before_connect() -> None:
    called = False

    def factory(url: str, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    with pytest.raises(RuntimeError, match="expired"):
        await fetch_ninjatrader_demo_quote(
            binding=_binding(),
            auth=_auth(
                expiration_time_utc=datetime(
                    2020, 1, 1, tzinfo=UTC
                )
            ),
            connect_factory=factory,
        )
    assert called is False


@pytest.mark.asyncio
async def test_transport_rejects_non_ninjatrader_source_before_connect() -> None:
    called = False

    def factory(url: str, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    with pytest.raises(ValueError, match="primary source"):
        await fetch_ninjatrader_demo_quote(
            binding=_binding(primary_market_source_id="other.source"),
            auth=_auth(),
            connect_factory=factory,
        )
    assert called is False


@pytest.mark.asyncio
async def test_trade_print_requirement_waits_for_real_trade_event() -> None:
    bbo_only = {
        "e": "md",
        "d": {
            "quotes": [
                {
                    "timestamp": "2026-09-27T03:12:00.100Z",
                    "contractId": 987654,
                    "entries": {
                        "Bid": {"price": 6700.25},
                        "Offer": {"price": 6700.50},
                    },
                }
            ]
        },
    }
    trade = {
        "e": "md",
        "d": {
            "quotes": [
                {
                    "timestamp": "2026-09-27T03:12:00.200Z",
                    "contractId": 987654,
                    "entries": {
                        "Trade": {"price": 6700.50, "size": 4},
                    },
                }
            ]
        },
    }
    _, _, factory = _connect(
        [
            "o",
            'a[{"s":200,"i":1}]',
            'a[{"s":200,"i":2}]',
            "a" + json.dumps([bbo_only], separators=(",", ":")),
            "a" + json.dumps([trade], separators=(",", ":")),
        ]
    )

    sample = await fetch_ninjatrader_demo_quote(
        binding=_binding(),
        auth=_auth(),
        timeout_s=1.0,
        require_trade_print=True,
        connect_factory=factory,
    )

    assert sample.trade_print is not None
    assert sample.trade_print.price == 6700.50
    assert sample.trade_print.volume == 4
