from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from aether_vnext.kraken_public import (
    KRAKEN_PUBLIC_WS_V2_URL,
    fetch_kraken_public_tickers,
    kraken_ticker_subscription,
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
            raise RuntimeError("fake websocket exhausted")
        return self.messages.pop(0)


def _online() -> dict:
    return {
        "channel": "status",
        "type": "update",
        "data": [
            {
                "system": "online",
                "api_version": "v2",
                "connection_id": 12345,
            }
        ],
    }


def _ack() -> dict:
    return {
        "method": "subscribe",
        "success": True,
        "result": {
            "channel": "ticker",
            "symbol": "BTC/USD",
            "snapshot": True,
        },
        "req_id": 1,
    }


def _ticker(symbol: str, px: float, timestamp: str) -> dict:
    return {
        "channel": "ticker",
        "type": "snapshot",
        "data": [
            {
                "symbol": symbol,
                "bid": px - 1.0,
                "ask": px + 1.0,
                "last": px,
                "timestamp": timestamp,
            }
        ],
    }


def test_subscription_is_public_v2_bbo_snapshot_contract() -> None:
    request = kraken_ticker_subscription(
        symbols=("BTC/USD", "ETH/USD"),
        req_id=7,
    )
    assert request == {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": ["BTC/USD", "ETH/USD"],
            "event_trigger": "bbo",
            "snapshot": True,
        },
        "req_id": 7,
    }


@pytest.mark.asyncio
async def test_fetch_collects_btc_eth_after_online_status_and_subscription_ack() -> None:
    socket = FakeWebSocket(
        [
            _online(),
            {"channel": "heartbeat"},
            _ack(),
            _ticker("BTC/USD", 100000.0, "2026-09-27T02:00:00.100000Z"),
            _ticker("ETH/USD", 4000.0, "2026-09-27T02:00:00.200000Z"),
        ]
    )
    calls = []

    def connect_factory(url: str, **kwargs):
        calls.append((url, kwargs))
        return socket

    batch = await fetch_kraken_public_tickers(
        assets=("btc", "eth"),
        timeout_s=1.0,
        connect_factory=connect_factory,
    )

    assert calls[0][0] == KRAKEN_PUBLIC_WS_V2_URL
    assert batch.status_system == "online"
    assert batch.status_api_version == "v2"
    assert batch.connection_id == 12345
    assert batch.subscription_acknowledged is True
    assert batch.heartbeat_count == 1
    assert tuple(row.asset_id for row in batch.quotes) == ("btc", "eth")
    assert batch.quotes[0].bid == 99999.0
    assert batch.quotes[0].ask == 100001.0
    assert batch.quotes[0].mark == 100000.0
    assert batch.quotes[0].exchange_ts == datetime(
        2026, 9, 27, 2, 0, 0, 100000, tzinfo=UTC
    )
    assert batch.quotes[1].source_id == "kraken_public"

    sent = json.loads(socket.sent[0])
    assert sent["params"]["event_trigger"] == "bbo"
    assert sent["params"]["symbol"] == ["BTC/USD", "ETH/USD"]


@pytest.mark.asyncio
async def test_non_online_kraken_status_fails_closed() -> None:
    socket = FakeWebSocket(
        [
            {
                "channel": "status",
                "type": "update",
                "data": [
                    {
                        "system": "maintenance",
                        "api_version": "v2",
                        "connection_id": 99,
                    }
                ],
            }
        ]
    )

    def connect_factory(url: str, **kwargs):
        return socket

    with pytest.raises(RuntimeError, match="kraken_exchange_status:maintenance"):
        await fetch_kraken_public_tickers(
            assets=("btc",),
            timeout_s=1.0,
            connect_factory=connect_factory,
        )


@pytest.mark.asyncio
async def test_subscription_error_fails_closed() -> None:
    socket = FakeWebSocket(
        [
            _online(),
            {
                "method": "subscribe",
                "success": False,
                "error": "unsupported pair",
                "req_id": 1,
            },
        ]
    )

    def connect_factory(url: str, **kwargs):
        return socket

    with pytest.raises(
        RuntimeError,
        match="kraken_ticker_subscription_failed:unsupported pair",
    ):
        await fetch_kraken_public_tickers(
            assets=("btc",),
            timeout_s=1.0,
            connect_factory=connect_factory,
        )


@pytest.mark.asyncio
async def test_unknown_aether_asset_never_opens_websocket() -> None:
    called = False

    def connect_factory(url: str, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    with pytest.raises(ValueError, match="unsupported AETHER Kraken asset"):
        await fetch_kraken_public_tickers(
            assets=("sol",),
            connect_factory=connect_factory,
        )

    assert called is False
