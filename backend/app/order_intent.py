"""Two-phase paper execution. Phase A reserves locally. Phase B is async fill.

A SQL transaction must never stay open waiting on a venue ack.
Paper still emits SUBMITTED then FILLED (or REJECTED / CANCELLED_STALE).
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from app.fill_model import SLIPPAGE_BPS, modeled_fill_price
from app.sleeves import SleeveBook, sleeve_for_asset

IntentState = Literal[
    "RESERVED",
    "SUBMITTED",
    "FILLED",
    "REJECTED",
    "CANCELLED",
    "CANCELLED_STALE",
]

PAPER_ACK_MS = 250
SUBMIT_TIMEOUT_MS = 15_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def idempotency_key(
    ticket_id: str,
    side: str,
    qty: float,
    asset_id: str,
    horizon: str,
    signal_key: str,
) -> str:
    raw = "|".join(
        [
            str(ticket_id),
            str(side).lower(),
            str(qty),
            str(asset_id).lower(),
            str(horizon).lower(),
            str(signal_key),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class OrderIntent:
    order_intent_id: str
    ticket_id: str
    asset_id: str
    horizon: str
    side: str
    quantity: float
    reserved_usd: float
    signal_key: str
    idempotency_key: str
    state: IntentState
    sleeve_id: str
    created_at: str
    submitted_at: str | None = None
    filled_at: str | None = None
    fill_price: float | None = None
    filled_qty: float = 0.0
    reject_code: str | None = None
    consumed_signal: bool = False
    events: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


class TwoPhaseExecutor:
    """In-memory paper adapter. Same event shape a live adapter must emit."""

    def __init__(
        self,
        sleeves: SleeveBook,
        *,
        paper_ack_ms: int = PAPER_ACK_MS,
        submit_timeout_ms: int = SUBMIT_TIMEOUT_MS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.sleeves = sleeves
        self.paper_ack_ms = int(paper_ack_ms)
        self.submit_timeout_ms = int(submit_timeout_ms)
        self._mono = clock or time.monotonic
        self.intents: dict[str, OrderIntent] = {}
        self.by_idempotency: dict[str, str] = {}
        self.consumed_signals: set[str] = set()
        self._submitted_at_mono: dict[str, float] = {}

    def reserve(
        self,
        *,
        ticket_id: str,
        asset_id: str,
        horizon: str,
        side: str,
        quantity: float,
        reserved_usd: float,
        signal_key: str,
    ) -> dict[str, Any]:
        key = idempotency_key(
            ticket_id, side, quantity, asset_id, horizon, signal_key
        )
        existing_id = self.by_idempotency.get(key)
        if existing_id:
            intent = self.intents[existing_id]
            return {"ok": True, "duplicate": True, **intent.snapshot()}
        if signal_key in self.consumed_signals:
            return {"ok": False, "error": "signal_consumed", "signal_key": signal_key}
        intent_id = uuid.uuid4().hex
        held = self.sleeves.reserve(asset_id, reserved_usd, intent_id=intent_id)
        if not held.get("ok"):
            return held
        intent = OrderIntent(
            order_intent_id=intent_id,
            ticket_id=str(ticket_id),
            asset_id=str(asset_id).lower(),
            horizon=str(horizon).lower(),
            side=str(side).lower(),
            quantity=float(quantity),
            reserved_usd=float(reserved_usd),
            signal_key=str(signal_key),
            idempotency_key=key,
            state="RESERVED",
            sleeve_id=sleeve_for_asset(asset_id),
            created_at=_now(),
            events=["RESERVED"],
        )
        self.intents[intent_id] = intent
        self.by_idempotency[key] = intent_id
        return {"ok": True, "duplicate": False, **intent.snapshot()}

    def submit(self, order_intent_id: str) -> dict[str, Any]:
        intent = self.intents.get(order_intent_id)
        if intent is None:
            return {"ok": False, "error": "unknown_intent"}
        if intent.state != "RESERVED":
            return {"ok": False, "error": "illegal_state", "state": intent.state}
        intent.state = "SUBMITTED"
        intent.submitted_at = _now()
        intent.events.append("SUBMITTED")
        self._submitted_at_mono[intent.order_intent_id] = self._mono()
        return {"ok": True, **intent.snapshot()}

    def fill(
        self,
        order_intent_id: str,
        *,
        bid: float | None,
        ask: float | None,
        mark: float | None,
        hard_stop: float | None = None,
    ) -> dict[str, Any]:
        intent = self.intents.get(order_intent_id)
        if intent is None:
            return {"ok": False, "error": "unknown_intent"}
        if intent.state != "SUBMITTED":
            return {"ok": False, "error": "illegal_state", "state": intent.state}
        exec_side = "buy" if intent.side == "long" else "sell"
        px = modeled_fill_price(exec_side, bid=bid, ask=ask, mark=mark)
        if px is None:
            return self._reject(intent, "market_stale")
        if hard_stop is not None:
            if intent.side == "long" and bid is not None and float(bid) <= float(hard_stop):
                return self._reject(intent, "market_changed")
            if intent.side == "short" and ask is not None and float(ask) >= float(hard_stop):
                return self._reject(intent, "market_changed")
            if intent.side == "long" and px <= float(hard_stop):
                return self._reject(intent, "bad_fill_through_stop")
            if intent.side == "short" and px >= float(hard_stop):
                return self._reject(intent, "bad_fill_through_stop")
        if intent.signal_key in self.consumed_signals:
            return self._reject(intent, "signal_consumed")
        self.sleeves.consume_reserve(intent.asset_id, intent.reserved_usd, leftover=0.0)
        self.consumed_signals.add(intent.signal_key)
        intent.consumed_signal = True
        intent.state = "FILLED"
        intent.filled_at = _now()
        intent.fill_price = float(px)
        intent.filled_qty = float(intent.quantity)
        intent.events.append("FILLED")
        return {"ok": True, **intent.snapshot(), "slippage_bps": SLIPPAGE_BPS}

    def reject(self, order_intent_id: str, code: str) -> dict[str, Any]:
        intent = self.intents.get(order_intent_id)
        if intent is None:
            return {"ok": False, "error": "unknown_intent"}
        return self._reject(intent, code)

    def expire_stale(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        now = self._mono()
        timeout_s = self.submit_timeout_ms / 1000.0
        for iid, started in list(self._submitted_at_mono.items()):
            intent = self.intents.get(iid)
            if intent is None or intent.state != "SUBMITTED":
                continue
            if now - started < timeout_s:
                continue
            self.sleeves.release(intent.asset_id, intent.reserved_usd)
            intent.state = "CANCELLED_STALE"
            intent.reject_code = "submit_timeout"
            intent.events.append("CANCELLED_STALE")
            out.append(intent.snapshot())
        return out

    def _reject(self, intent: OrderIntent, code: str) -> dict[str, Any]:
        if intent.state in {"RESERVED", "SUBMITTED"}:
            self.sleeves.release(intent.asset_id, intent.reserved_usd)
        intent.state = "REJECTED"
        intent.reject_code = code
        intent.events.append(f"REJECTED:{code}")
        return {"ok": False, "error": code, **intent.snapshot()}
