from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from aether_vnext.market_truth_kraken import (
    KRAKEN_EXECUTABLE_WS_V2_URL,
    KrakenExecutableAdapter,
    collect_kraken_executable_sample,
    replay_kraken_capture,
)
from aether_vnext.market_truth_route import RouteRecord


UTC = timezone.utc
NOW = datetime(2026, 10, 4, 21, 0, tzinfo=UTC)


class FakeSocket:
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
            raise RuntimeError("fake socket exhausted")
        return self.messages.pop(0)


def _route() -> RouteRecord:
    return RouteRecord(
        canonical_instrument_id="btc-usd",
        executable_provider_id="kraken",
        witness_provider_ids=(),
        human_set_by="operator",
        human_set_at_utc=NOW,
        route_revision=1,
    )


def _messages() -> list[dict]:
    return [
        {
            "channel": "status",
            "type": "update",
            "data": [{"system": "online", "api_version": "v2", "connection_id": 42}],
        },
        {
            "method": "subscribe",
            "success": True,
            "result": {"channel": "ticker", "symbol": "BTC/USD"},
            "req_id": 1,
        },
        {
            "channel": "ticker",
            "type": "snapshot",
            "data": [{
                "symbol": "BTC/USD",
                "bid": 65000.0,
                "ask": 65001.0,
                "last": 65000.5,
                "bid_qty": 1.2,
                "ask_qty": 0.8,
                "timestamp": "2026-10-04T21:00:00Z",
            }],
        },
    ]


def test_kraken_adapter_is_parser_only_and_preserves_printed_fields() -> None:
    adapter = KrakenExecutableAdapter(symbol="BTC/USD", canonical_instrument_id="btc-usd")
    packet = adapter.parse(_messages()[-1], received_at_utc=NOW)
    assert packet is not None
    assert packet.bid == 65000.0
    assert packet.ask == 65001.0
    assert packet.last_if_printed == 65000.5
    assert packet.bid_size == 1.2
    assert packet.ask_size == 0.8
    assert "mark" not in packet.__dataclass_fields__
    assert "mid" not in packet.__dataclass_fields__


def test_missing_kraken_field_stays_null_never_zero() -> None:
    payload = _messages()[-1]
    del payload["data"][0]["last"]
    del payload["data"][0]["bid_qty"]
    packet = KrakenExecutableAdapter(
        symbol="BTC/USD", canonical_instrument_id="btc-usd"
    ).parse(payload, received_at_utc=NOW)
    assert packet is not None
    assert packet.last_if_printed is None
    assert packet.bid_size is None


@pytest.mark.asyncio
async def test_public_socket_sample_captures_raw_packets_for_replay() -> None:
    socket = FakeSocket(_messages())
    calls = []

    def connect(url: str, **kwargs):
        calls.append((url, kwargs))
        return socket

    sample = await collect_kraken_executable_sample(
        _route(), symbol="BTC/USD", timeout_s=1.0, connect_factory=connect
    )
    assert calls[0][0] == KRAKEN_EXECUTABLE_WS_V2_URL
    assert sample.connection_id == 42
    assert sample.executable_packet.bid == 65000.0
    assert len(sample.captures) == 3

    sent = json.loads(socket.sent[0])
    assert sent["params"]["event_trigger"] == "bbo"
    assert sent["params"]["symbol"] == ["BTC/USD"]

    replayed = replay_kraken_capture(
        KrakenExecutableAdapter(symbol="BTC/USD", canonical_instrument_id="btc-usd"),
        sample.captures,
    )
    assert len(replayed) == 1
    assert replayed[0].bid == sample.executable_packet.bid
    assert replayed[0].ask == sample.executable_packet.ask
    assert replayed[0].last_if_printed == sample.executable_packet.last_if_printed


@pytest.mark.asyncio
async def test_kraken_adapter_refuses_other_route_provider() -> None:
    route = RouteRecord(
        canonical_instrument_id="btc-usd",
        executable_provider_id="other",
        witness_provider_ids=(),
        human_set_by="operator",
        human_set_at_utc=NOW,
        route_revision=1,
    )
    with pytest.raises(ValueError, match="different route provider"):
        await collect_kraken_executable_sample(
            route, symbol="BTC/USD", timeout_s=1.0, connect_factory=lambda *_a, **_k: None
        )
