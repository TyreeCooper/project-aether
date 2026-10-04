"""Layer 4A: executable Market Fabric state machine.

This module accepts already-parsed provider packets from the human-selected Route.
It never averages, synthesizes, interpolates, carries forward, or replaces prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from aether_vnext.market_truth_contract import ExecutionState
from aether_vnext.market_truth_provider import ProviderCardRegistry
from aether_vnext.market_truth_route import RouteRecord


UTC = timezone.utc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("market timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _positive_or_none(name: str, value: float | None) -> None:
    if value is not None and (not isfinite(value) or value <= 0):
        raise ValueError(f"{name} must be positive and finite when present")


@dataclass(frozen=True, slots=True)
class ParsedExecutablePacket:
    """Provider-authored fields only. No derived values are allowed here."""

    canonical_instrument_id: str
    provider_id: str
    venue: str
    transport_id: str
    bid: float | None
    ask: float | None
    last_if_printed: float | None
    bid_size: float | None
    ask_size: float | None
    venue_time_utc: datetime | None
    receive_time_utc: datetime

    def __post_init__(self) -> None:
        for name in (
            "canonical_instrument_id", "provider_id", "venue", "transport_id"
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        _positive_or_none("bid", self.bid)
        _positive_or_none("ask", self.ask)
        _positive_or_none("last_if_printed", self.last_if_printed)
        _positive_or_none("bid_size", self.bid_size)
        _positive_or_none("ask_size", self.ask_size)
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("provider executable book is crossed")
        if self.venue_time_utc is not None:
            _utc(self.venue_time_utc)
        _utc(self.receive_time_utc)


@dataclass(frozen=True, slots=True)
class ExecutableBookSnapshot:
    canonical_instrument_id: str
    route_id: str
    executable_provider_id: str
    venue: str
    transport_id: str | None
    state: ExecutionState
    bid: float | None
    ask: float | None
    last_if_printed: float | None
    bid_size: float | None
    ask_size: float | None
    venue_time_utc: datetime | None
    receive_time_utc: datetime | None
    state_reason: str

    def __post_init__(self) -> None:
        if self.state is ExecutionState.EXECUTABLE:
            if self.bid is None or self.ask is None:
                raise ValueError("EXECUTABLE requires provider bid and ask")
            if self.transport_id is None:
                raise ValueError("EXECUTABLE requires active transport")
        else:
            # A non-executable route cannot leak a stale/carried price into execution.
            for field in ("bid", "ask", "last_if_printed", "bid_size", "ask_size"):
                if getattr(self, field) is not None:
                    raise ValueError(f"{self.state.value} must blank {field}")

    @classmethod
    def not_observed(cls, route: RouteRecord, *, venue: str, reason: str) -> "ExecutableBookSnapshot":
        return cls(
            canonical_instrument_id=route.canonical_instrument_id,
            route_id=route.route_id,
            executable_provider_id=route.executable_provider_id,
            venue=venue,
            transport_id=None,
            state=ExecutionState.NOT_OBSERVED,
            bid=None,
            ask=None,
            last_if_printed=None,
            bid_size=None,
            ask_size=None,
            venue_time_utc=None,
            receive_time_utc=None,
            state_reason=reason,
        )


def apply_executable_packet(
    route: RouteRecord,
    packet: ParsedExecutablePacket,
    *,
    providers: ProviderCardRegistry,
    as_of_utc: datetime,
    stale_after_ms: int,
) -> ExecutableBookSnapshot:
    """Publish route truth exactly as printed or fail closed with blank prices."""
    if stale_after_ms <= 0:
        raise ValueError("stale_after_ms must be positive")
    as_of = _utc(as_of_utc)
    selected = providers.require(route.executable_provider_id)
    if not selected.can_execute:
        raise ValueError("route provider lacks execute capability")
    if packet.canonical_instrument_id.strip().lower() != route.canonical_instrument_id.strip().lower():
        raise ValueError("packet instrument does not match Route")
    if packet.provider_id.strip().lower() != route.executable_provider_id.strip().lower():
        raise ValueError("packet provider does not own Route")
    if packet.venue.strip().lower() != selected.venue.strip().lower():
        raise ValueError("packet venue does not match Route provider card")

    age_ms = max(0, int((as_of - _utc(packet.receive_time_utc)).total_seconds() * 1000))
    if age_ms > stale_after_ms:
        return ExecutableBookSnapshot(
            canonical_instrument_id=route.canonical_instrument_id,
            route_id=route.route_id,
            executable_provider_id=route.executable_provider_id,
            venue=selected.venue,
            transport_id=packet.transport_id,
            state=ExecutionState.STALE,
            bid=None,
            ask=None,
            last_if_printed=None,
            bid_size=None,
            ask_size=None,
            venue_time_utc=packet.venue_time_utc,
            receive_time_utc=packet.receive_time_utc,
            state_reason="executable_packet_stale",
        )
    if packet.bid is None or packet.ask is None:
        return ExecutableBookSnapshot(
            canonical_instrument_id=route.canonical_instrument_id,
            route_id=route.route_id,
            executable_provider_id=route.executable_provider_id,
            venue=selected.venue,
            transport_id=packet.transport_id,
            state=ExecutionState.NOT_OBSERVED,
            bid=None,
            ask=None,
            last_if_printed=None,
            bid_size=None,
            ask_size=None,
            venue_time_utc=packet.venue_time_utc,
            receive_time_utc=packet.receive_time_utc,
            state_reason="two_sided_executable_book_not_observed",
        )

    return ExecutableBookSnapshot(
        canonical_instrument_id=route.canonical_instrument_id,
        route_id=route.route_id,
        executable_provider_id=route.executable_provider_id,
        venue=selected.venue,
        transport_id=packet.transport_id,
        state=ExecutionState.EXECUTABLE,
        bid=packet.bid,
        ask=packet.ask,
        last_if_printed=packet.last_if_printed,
        bid_size=packet.bid_size,
        ask_size=packet.ask_size,
        venue_time_utc=packet.venue_time_utc,
        receive_time_utc=packet.receive_time_utc,
        state_reason="fresh_coherent_route_book",
    )


def refresh_executable_state(
    snapshot: ExecutableBookSnapshot,
    *,
    as_of_utc: datetime,
    stale_after_ms: int,
) -> ExecutableBookSnapshot:
    """Age an executable snapshot without carrying its price through STALE."""
    if snapshot.state is not ExecutionState.EXECUTABLE:
        return snapshot
    if snapshot.receive_time_utc is None:
        raise ValueError("EXECUTABLE snapshot missing receive timestamp")
    age_ms = max(0, int((_utc(as_of_utc) - _utc(snapshot.receive_time_utc)).total_seconds() * 1000))
    if age_ms <= stale_after_ms:
        return snapshot
    return ExecutableBookSnapshot(
        canonical_instrument_id=snapshot.canonical_instrument_id,
        route_id=snapshot.route_id,
        executable_provider_id=snapshot.executable_provider_id,
        venue=snapshot.venue,
        transport_id=snapshot.transport_id,
        state=ExecutionState.STALE,
        bid=None,
        ask=None,
        last_if_printed=None,
        bid_size=None,
        ask_size=None,
        venue_time_utc=snapshot.venue_time_utc,
        receive_time_utc=snapshot.receive_time_utc,
        state_reason="executable_transport_stale",
    )


def executable_transport_down(
    route: RouteRecord,
    *,
    providers: ProviderCardRegistry,
    reason: str = "executable_transport_down",
) -> ExecutableBookSnapshot:
    """Cable-pull semantics: route price disappears; no witness fallback exists here."""
    selected = providers.require(route.executable_provider_id)
    return ExecutableBookSnapshot.not_observed(
        route,
        venue=selected.venue,
        reason=reason,
    )
