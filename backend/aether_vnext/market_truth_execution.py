"""Layer 5: route-bound AETHER PAPER execution.

Execution consumes only the human Route, executable book, Provider Card fee, and
explicit PAPER simulation controls. Witness evidence is intentionally absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from math import isfinite

from aether_vnext.market_fabric_paper_fill import (
    DepthLevel,
    PaperFillPolicy,
    PaperFillResult,
    simulate_paper_fill,
)
from aether_vnext.market_truth_contract import ExecutionState
from aether_vnext.market_truth_fabric import ExecutableBookSnapshot
from aether_vnext.market_truth_provider import ProviderCardRegistry
from aether_vnext.market_truth_route import RouteRecord


@dataclass(frozen=True, slots=True)
class PaperExecutionPolicy:
    policy_version: str
    modeled_latency_ms: int
    max_participation: float
    l1_quantity_cap: float | None
    reject_on_insufficient_depth: bool = True

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if self.modeled_latency_ms < 0:
            raise ValueError("modeled_latency_ms cannot be negative")
        if not isfinite(self.max_participation) or not 0 < self.max_participation <= 1:
            raise ValueError("max_participation must be in (0,1]")
        if self.l1_quantity_cap is not None and (
            not isfinite(self.l1_quantity_cap) or self.l1_quantity_cap <= 0
        ):
            raise ValueError("l1_quantity_cap must be positive when present")


@dataclass(frozen=True, slots=True)
class PaperExecutionFact:
    route_id: str
    canonical_instrument_id: str
    provider_id: str
    venue: str
    fee_schedule_id: str
    book_fingerprint: str
    book_receive_time_utc: datetime
    fill: PaperFillResult

    @property
    def live_execution_authorized(self) -> bool:
        return False


def executable_book_fingerprint(book: ExecutableBookSnapshot) -> str:
    payload = {
        "route_id": book.route_id,
        "instrument": book.canonical_instrument_id,
        "provider": book.executable_provider_id,
        "venue": book.venue,
        "transport": book.transport_id,
        "state": book.state.value,
        "bid": book.bid,
        "ask": book.ask,
        "last_if_printed": book.last_if_printed,
        "bid_size": book.bid_size,
        "ask_size": book.ask_size,
        "venue_time_utc": None if book.venue_time_utc is None else book.venue_time_utc.isoformat(),
        "receive_time_utc": None if book.receive_time_utc is None else book.receive_time_utc.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def execute_paper_against_route_book(
    *,
    route: RouteRecord,
    book: ExecutableBookSnapshot,
    providers: ProviderCardRegistry,
    side: str,
    quantity: float,
    policy: PaperExecutionPolicy,
) -> PaperExecutionFact:
    """Walk the live executable top of book or reject; never substitute another price."""
    if book.state is not ExecutionState.EXECUTABLE:
        raise RuntimeError(f"paper execution requires EXECUTABLE book, got {book.state.value}")
    if book.route_id != route.route_id:
        raise RuntimeError("paper execution book Route mismatch")
    if (
        book.canonical_instrument_id.strip().lower()
        != route.canonical_instrument_id.strip().lower()
    ):
        raise RuntimeError("paper execution instrument mismatch")
    if (
        book.executable_provider_id.strip().lower()
        != route.executable_provider_id.strip().lower()
    ):
        raise RuntimeError("paper execution provider does not own Route")
    if book.bid is None or book.ask is None:
        raise RuntimeError("paper execution bid/ask unavailable")
    if book.receive_time_utc is None:
        raise RuntimeError("paper execution book timestamp unavailable")

    card = providers.require(route.executable_provider_id)
    if not card.can_execute:
        raise RuntimeError("Route Provider Card lacks execute capability")
    if card.venue.strip().lower() != book.venue.strip().lower():
        raise RuntimeError("Route Provider Card venue mismatch")
    fee_bps = card.fee_schedule.taker_bps
    if fee_bps is None:
        raise RuntimeError("Provider Card executable fee is NOT_OBSERVED")

    normalized_side = str(side).strip().upper()
    if normalized_side == "BUY":
        if book.ask_size is None:
            bid_levels: tuple[DepthLevel, ...] = ()
            ask_levels: tuple[DepthLevel, ...] = ()
        else:
            bid_levels = (
                () if book.bid_size is None
                else (DepthLevel(price=float(book.bid), size=float(book.bid_size)),)
            )
            ask_levels = (DepthLevel(price=float(book.ask), size=float(book.ask_size)),)
    elif normalized_side == "SELL":
        if book.bid_size is None:
            bid_levels = ()
            ask_levels = ()
        else:
            bid_levels = (DepthLevel(price=float(book.bid), size=float(book.bid_size)),)
            ask_levels = (
                () if book.ask_size is None
                else (DepthLevel(price=float(book.ask), size=float(book.ask_size)),)
            )
    else:
        raise ValueError("side must be BUY or SELL")

    fill = simulate_paper_fill(
        side=normalized_side,
        quantity=quantity,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        policy=PaperFillPolicy(
            policy_version=policy.policy_version,
            modeled_latency_ms=policy.modeled_latency_ms,
            fee_bps=float(fee_bps),
            max_participation=policy.max_participation,
            l1_quantity_cap=policy.l1_quantity_cap,
            reject_on_insufficient_depth=policy.reject_on_insufficient_depth,
        ),
        l2_available=False,
    )
    return PaperExecutionFact(
        route_id=route.route_id,
        canonical_instrument_id=route.canonical_instrument_id,
        provider_id=card.provider_id,
        venue=card.venue,
        fee_schedule_id=card.fee_schedule.schedule_id,
        book_fingerprint=executable_book_fingerprint(book),
        book_receive_time_utc=book.receive_time_utc,
        fill=fill,
    )


def assert_execution_fact_matches_book(
    fact: PaperExecutionFact,
    book: ExecutableBookSnapshot,
) -> None:
    if fact.book_fingerprint != executable_book_fingerprint(book):
        raise RuntimeError("paper fill was not checked against the live book snapshot")
    if not fact.fill.accepted:
        return
    expected = book.ask if fact.fill.side == "BUY" else book.bid
    if expected is None or fact.fill.average_price != float(expected):
        raise RuntimeError("L1 PAPER fill price does not match executable route book")
