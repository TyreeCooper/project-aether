"""Public Coinbase Exchange witness socket for the first AETHER proof.

This is an observe-only adapter. It can never publish executable market truth.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable

import websockets

from aether_vnext.market_truth_evidence import WitnessObservation


UTC = timezone.utc
COINBASE_WITNESS_WS_URL = "wss://ws-feed.exchange.coinbase.com"
COINBASE_WITNESS_PROVIDER_ID = "coinbase"
COINBASE_WITNESS_VENUE = "Coinbase Exchange"


@dataclass(frozen=True, slots=True)
class CapturedWitnessPacket:
    sequence: int
    raw_text: str
    received_at_utc: datetime


@dataclass(frozen=True, slots=True)
class CoinbaseWitnessSocketSample:
    observation: WitnessObservation
    captures: tuple[CapturedWitnessPacket, ...]


class CoinbaseWitnessAdapter:
    provider_id = COINBASE_WITNESS_PROVIDER_ID
    venue = COINBASE_WITNESS_VENUE
    adapter_id = "market-truth.coinbase-witness-v1"

    def __init__(self, *, product_id: str, canonical_instrument_id: str) -> None:
        self.product_id = str(product_id).strip().upper()
        self.canonical_instrument_id = str(canonical_instrument_id).strip().lower()
        if not self.product_id or not self.canonical_instrument_id:
            raise ValueError("Coinbase product and instrument are required")

    def subscription_payload(self) -> dict[str, object]:
        return {
            "type": "subscribe",
            "product_ids": [self.product_id],
            "channels": ["ticker"],
        }

    def parse(self, payload: object, *, received_at_utc: datetime) -> WitnessObservation | None:
        if received_at_utc.tzinfo is None:
            raise ValueError("received_at_utc must be timezone-aware")
        if not isinstance(payload, dict) or payload.get("type") != "ticker":
            return None
        if str(payload.get("product_id") or "").strip().upper() != self.product_id:
            return None

        def num(name: str) -> float | None:
            raw = payload.get(name)
            return None if raw in (None, "") else float(raw)

        raw_time = payload.get("time")
        venue_time = None
        if raw_time not in (None, ""):
            text = str(raw_time)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            venue_time = datetime.fromisoformat(text)
            if venue_time.tzinfo is None:
                raise ValueError("Coinbase venue time must be timezone-aware")
            venue_time = venue_time.astimezone(UTC)

        return WitnessObservation(
            canonical_instrument_id=self.canonical_instrument_id,
            provider_id=self.provider_id,
            venue=self.venue,
            bid=num("best_bid"),
            ask=num("best_ask"),
            last_if_printed=num("price"),
            venue_time_utc=venue_time,
            receive_time_utc=received_at_utc.astimezone(UTC),
        )


async def collect_coinbase_witness_sample(
    *,
    product_id: str,
    canonical_instrument_id: str,
    timeout_s: float = 10.0,
    connect_factory: Callable[..., object] | None = None,
) -> CoinbaseWitnessSocketSample:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    adapter = CoinbaseWitnessAdapter(
        product_id=product_id,
        canonical_instrument_id=canonical_instrument_id,
    )
    connect = connect_factory or websockets.connect
    captures: list[CapturedWitnessPacket] = []

    async with connect(
        COINBASE_WITNESS_WS_URL,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
    ) as socket:
        await socket.send(json.dumps(adapter.subscription_payload(), sort_keys=True, separators=(",", ":")))
        async with asyncio.timeout(timeout_s):
            while True:
                raw = await socket.recv()
                received = datetime.now(UTC)
                text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                captures.append(CapturedWitnessPacket(len(captures) + 1, text, received))
                payload = json.loads(text)
                if isinstance(payload, dict) and payload.get("type") == "error":
                    raise RuntimeError(f"Coinbase witness subscription error: {payload.get('message')}")
                observation = adapter.parse(payload, received_at_utc=received)
                if observation is not None:
                    return CoinbaseWitnessSocketSample(
                        observation=observation,
                        captures=tuple(captures),
                    )
