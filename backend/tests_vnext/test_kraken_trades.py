from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from aether_vnext.adapters import KrakenPublicTradeV2
from aether_vnext.bars import ClosedBarBuilder
from aether_vnext.kraken_public import (
    KRAKEN_PUBLIC_TRADE_SOURCE_ID,
    KRAKEN_PUBLIC_WS_V2_URL,
    fetch_kraken_public_trades,
    kraken_trade_subscription,
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
            raise RuntimeError("fake Kraken trade websocket exhausted")
        return self.messages.pop(0)


def _online() -> dict:
    return {
        "channel": "status",
        "type": "update",
        "data": [
            {
                "system": "online",
                "api_version": "v2",
                "connection_id": 98765,
            }
        ],
    }


def _trade_ack() -> dict:
    return {
        "method": "subscribe",
        "success": True,
        "result": {
            "channel": "trade",
            "symbol": "BTC/USD",
            "snapshot": False,
        },
        "req_id": 2,
    }


def _trade(
    symbol: str,
    *,
    price: float,
    qty: float,
    timestamp: str,
    trade_id: int,
) -> dict:
    return {
        "channel": "trade",
        "type": "update",
        "data": [
            {
                "symbol": symbol,
                "side": "buy",
                "qty": qty,
                "price": price,
                "ord_type": "market",
                "trade_id": trade_id,
                "timestamp": timestamp,
            }
        ],
    }


def test_trade_subscription_requests_new_matched_trades_without_snapshot() -> None:
    request = kraken_trade_subscription(
        symbols=("BTC/USD", "ETH/USD"),
        req_id=9,
    )
    assert request == {
        "method": "subscribe",
        "params": {
            "channel": "trade",
            "symbol": ["BTC/USD", "ETH/USD"],
            "snapshot": False,
        },
        "req_id": 9,
    }


def test_trade_adapter_maps_price_qty_and_exchange_timestamp_to_market_print() -> None:
    adapter = KrakenPublicTradeV2()
    received = datetime(2026, 9, 27, 6, 30, 1, tzinfo=UTC)
    rows = adapter.parse_prints(
        {
            "channel": "trade",
            "type": "update",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "price": 100000.5,
                    "qty": 0.125,
                    "timestamp": "2026-09-27T06:30:00.100000Z",
                },
                {
                    "symbol": "ETH/USD",
                    "price": 4000.25,
                    "qty": 2.5,
                    "timestamp": "2026-09-27T06:30:00.200000Z",
                },
                {
                    "symbol": "SOL/USD",
                    "price": 200.0,
                    "qty": 1.0,
                    "timestamp": "2026-09-27T06:30:00.300000Z",
                },
            ],
        },
        received_at_utc=received,
    )

    assert tuple(row.asset_id for row in rows) == ("btc", "eth")
    assert rows[0].price == pytest.approx(100000.5)
    assert rows[0].volume == pytest.approx(0.125)
    assert rows[0].exchange_ts == datetime(
        2026, 9, 27, 6, 30, 0, 100000, tzinfo=UTC
    )
    assert rows[0].received_ts == received
    assert rows[0].source_id == KRAKEN_PUBLIC_TRADE_SOURCE_ID


@pytest.mark.asyncio
async def test_trade_fetch_requires_online_ack_and_one_new_trade_per_asset() -> None:
    socket = FakeWebSocket(
        [
            _online(),
            {"channel": "heartbeat"},
            _trade_ack(),
            _trade(
                "BTC/USD",
                price=100000.0,
                qty=0.1,
                timestamp="2026-09-27T06:31:00.100000Z",
                trade_id=10,
            ),
            _trade(
                "ETH/USD",
                price=4000.0,
                qty=1.5,
                timestamp="2026-09-27T06:31:00.200000Z",
                trade_id=11,
            ),
        ]
    )
    calls = []

    def connect_factory(url: str, **kwargs):
        calls.append((url, kwargs))
        return socket

    batch = await fetch_kraken_public_trades(
        assets=("btc", "eth"),
        timeout_s=1.0,
        connect_factory=connect_factory,
    )

    assert calls[0][0] == KRAKEN_PUBLIC_WS_V2_URL
    assert batch.status_system == "online"
    assert batch.status_api_version == "v2"
    assert batch.connection_id == 98765
    assert batch.subscription_acknowledged is True
    assert batch.heartbeat_count == 1
    assert tuple(row.asset_id for row in batch.prints) == ("btc", "eth")

    sent = json.loads(socket.sent[0])
    assert sent["params"]["channel"] == "trade"
    assert sent["params"]["snapshot"] is False
    assert sent["params"]["symbol"] == ["BTC/USD", "ETH/USD"]


def test_trade_prints_drive_real_closed_bar_without_synthetic_empty_bucket() -> None:
    adapter = KrakenPublicTradeV2()
    received = datetime(2026, 9, 27, 6, 32, 1, tzinfo=UTC)
    prints = adapter.parse_prints(
        {
            "channel": "trade",
            "type": "update",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "price": 100.0,
                    "qty": 2.0,
                    "timestamp": "2026-09-27T06:30:10Z",
                },
                {
                    "symbol": "BTC/USD",
                    "price": 101.0,
                    "qty": 3.0,
                    "timestamp": "2026-09-27T06:30:50Z",
                },
                {
                    "symbol": "BTC/USD",
                    "price": 102.0,
                    "qty": 4.0,
                    "timestamp": "2026-09-27T06:31:01Z",
                },
            ],
        },
        received_at_utc=received,
    )
    builder = ClosedBarBuilder(
        asset_id="btc",
        interval=timedelta(minutes=1),
        venue_timezone="UTC",
    )

    closed = []
    for print_ in prints:
        closed.extend(builder.push(print_))

    assert len(closed) == 1
    bar = closed[0]
    assert bar.open == pytest.approx(100.0)
    assert bar.high == pytest.approx(101.0)
    assert bar.low == pytest.approx(100.0)
    assert bar.close == pytest.approx(101.0)
    assert bar.volume == pytest.approx(5.0)
    assert bar.print_count == 2
    assert bar.bucket_open_utc == datetime(2026, 9, 27, 6, 30, tzinfo=UTC)
    assert bar.bucket_close_utc == datetime(2026, 9, 27, 6, 31, tzinfo=UTC)
    assert builder.forming_bar is not None
    assert builder.forming_bar.open == pytest.approx(102.0)


@pytest.mark.asyncio
async def test_trade_subscription_failure_and_exchange_maintenance_fail_closed() -> None:
    failed = FakeWebSocket(
        [
            _online(),
            {
                "method": "subscribe",
                "success": False,
                "error": "trade feed unavailable",
                "req_id": 2,
            },
        ]
    )

    with pytest.raises(
        RuntimeError,
        match="kraken_trade_subscription_failed:trade feed unavailable",
    ):
        await fetch_kraken_public_trades(
            assets=("btc",),
            timeout_s=1.0,
            connect_factory=lambda *args, **kwargs: failed,
        )

    maintenance = FakeWebSocket(
        [
            {
                "channel": "status",
                "type": "update",
                "data": [
                    {
                        "system": "maintenance",
                        "api_version": "v2",
                        "connection_id": 1,
                    }
                ],
            }
        ]
    )
    with pytest.raises(RuntimeError, match="kraken_exchange_status:maintenance"):
        await fetch_kraken_public_trades(
            assets=("btc",),
            timeout_s=1.0,
            connect_factory=lambda *args, **kwargs: maintenance,
        )
