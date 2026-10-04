"""Layer 4B: Kraken public WebSocket executable-route adapter.

The adapter parses provider packets only. It performs no midpoint, mark, composite,
fallback, carry-forward, witness, strategy, or fill calculation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Protocol

import websockets

from aether_vnext.market_truth_fabric import ParsedExecutablePacket
from aether_vnext.market_truth_route import RouteRecord


UTC = timezone.utc
KRAKEN_EXECUTABLE_WS_V2_URL = "wss://ws.kraken.com/v2"
KRAKEN_EXECUTABLE_PROVIDER_ID = "kraken"
KRAKEN_EXECUTABLE_VENUE = "Kraken"
KRAKEN_EXECUTABLE_TRANSPORT_ID = "kraken-public-ws-v2-primary"


class _SocketLike(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc, tb): ...


@dataclass(frozen=True, slots=True)
class CapturedProviderPacket:
    sequence: int
    raw_text: str
    received_at_utc: datetime

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("capture sequence must be >= 1")
        if not self.raw_text:
            raise ValueError("captured raw_text is required")
        if self.received_at_utc.tzinfo is None:
            raise ValueError("capture timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class KrakenExecutableSocketSample:
    executable_packet: ParsedExecutablePacket
    captures: tuple[CapturedProviderPacket, ...]
    connection_id: int | None


def _parse_time(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("Kraken venue timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _number_or_none(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


class KrakenExecutableAdapter:
    provider_id = KRAKEN_EXECUTABLE_PROVIDER_ID
    venue = KRAKEN_EXECUTABLE_VENUE
    transport_id = KRAKEN_EXECUTABLE_TRANSPORT_ID
    adapter_id = "market-truth.kraken-executable-v1"

    def __init__(self, *, symbol: str, canonical_instrument_id: str) -> None:
        self.symbol = str(symbol).strip().upper()
        self.canonical_instrument_id = str(canonical_instrument_id).strip().lower()
        if not self.symbol or not self.canonical_instrument_id:
            raise ValueError("Kraken adapter symbol and instrument id are required")

    def subscription_payload(self) -> dict[str, object]:
        return {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": [self.symbol],
                "event_trigger": "bbo",
                "snapshot": True,
            },
            "req_id": 1,
        }

    def parse(self, payload: object, *, received_at_utc: datetime) -> ParsedExecutablePacket | None:
        if received_at_utc.tzinfo is None:
            raise ValueError("received_at_utc must be timezone-aware")
        if not isinstance(payload, dict) or payload.get("channel") != "ticker":
            return None
        rows = payload.get("data")
        if not isinstance(rows, list):
            return None
        row = next(
            (
                item for item in rows
                if isinstance(item, dict)
                and str(item.get("symbol") or "").strip().upper() == self.symbol
            ),
            None,
        )
        if row is None:
            return None

        # Presence is preserved exactly. Missing provider fields become None.
        return ParsedExecutablePacket(
            canonical_instrument_id=self.canonical_instrument_id,
            provider_id=self.provider_id,
            venue=self.venue,
            transport_id=self.transport_id,
            bid=_number_or_none(row.get("bid")),
            ask=_number_or_none(row.get("ask")),
            last_if_printed=_number_or_none(row.get("last")),
            bid_size=_number_or_none(row.get("bid_qty")),
            ask_size=_number_or_none(row.get("ask_qty")),
            venue_time_utc=_parse_time(row.get("timestamp") or row.get("time")),
            receive_time_utc=received_at_utc.astimezone(UTC),
        )


def _decode(raw: str | bytes) -> tuple[str, object]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return text, json.loads(text)


def _online_status(payload: object) -> tuple[bool, int | None] | None:
    if not isinstance(payload, dict) or payload.get("channel") != "status":
        return None
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    return str(row.get("system") or "").lower() == "online", (
        None if row.get("connection_id") is None else int(row["connection_id"])
    )


def _subscription_ack(payload: object) -> bool | None:
    if not isinstance(payload, dict) or payload.get("method") != "subscribe":
        return None
    if payload.get("success") is None:
        return None
    return bool(payload.get("success"))


async def collect_kraken_executable_sample(
    route: RouteRecord,
    *,
    symbol: str,
    timeout_s: float = 10.0,
    connect_factory: Callable[..., object] | None = None,
) -> KrakenExecutableSocketSample:
    """Collect one fresh public executable BBO sample for the selected Kraken Route."""
    if route.executable_provider_id.strip().lower() != KRAKEN_EXECUTABLE_PROVIDER_ID:
        raise ValueError("Kraken executable adapter cannot serve a different route provider")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    adapter = KrakenExecutableAdapter(
        symbol=symbol,
        canonical_instrument_id=route.canonical_instrument_id,
    )
    connect = connect_factory or websockets.connect
    captures: list[CapturedProviderPacket] = []
    status_online = False
    subscription_ok = False
    connection_id: int | None = None

    async with connect(
        KRAKEN_EXECUTABLE_WS_V2_URL,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
    ) as socket:
        await socket.send(
            json.dumps(adapter.subscription_payload(), sort_keys=True, separators=(",", ":"))
        )
        async with asyncio.timeout(timeout_s):
            while True:
                raw = await socket.recv()
                received = datetime.now(UTC)
                raw_text, payload = _decode(raw)
                captures.append(
                    CapturedProviderPacket(
                        sequence=len(captures) + 1,
                        raw_text=raw_text,
                        received_at_utc=received,
                    )
                )

                status = _online_status(payload)
                if status is not None:
                    status_online, connection_id = status
                    if not status_online:
                        raise RuntimeError("Kraken executable venue is not online")
                    continue

                ack = _subscription_ack(payload)
                if ack is not None:
                    if not ack:
                        raise RuntimeError("Kraken executable subscription rejected")
                    subscription_ok = True
                    continue

                packet = adapter.parse(payload, received_at_utc=received)
                if packet is not None and status_online and subscription_ok:
                    return KrakenExecutableSocketSample(
                        executable_packet=packet,
                        captures=tuple(captures),
                        connection_id=connection_id,
                    )


def replay_kraken_capture(
    adapter: KrakenExecutableAdapter,
    captures: tuple[CapturedProviderPacket, ...],
) -> tuple[ParsedExecutablePacket, ...]:
    """Replay saved raw provider packets through the same parser without I/O."""
    out: list[ParsedExecutablePacket] = []
    for capture in sorted(captures, key=lambda row: row.sequence):
        _, payload = _decode(capture.raw_text)
        packet = adapter.parse(payload, received_at_utc=capture.received_at_utc)
        if packet is not None:
            out.append(packet)
    return tuple(out)
