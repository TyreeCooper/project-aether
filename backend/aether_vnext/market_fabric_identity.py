"""Canonical identity and route-authority contracts for AETHER Market Fabric v3.

This module implements the MF-01 constitutional identity split.  Market identity,
economic source, provider/transport delivery, execution authority, and effective
independence are deliberately separate concepts.

PAPER ONLY / LIVE HARD BLOCKED remain external invariants; nothing here can submit
orders or change runtime execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping


def _required_id(name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    if any(ch.isspace() for ch in normalized):
        raise ValueError(f"{name} cannot contain whitespace")
    return normalized


class SourceAuthorityClass(StrEnum):
    EXECUTABLE_ROUTE = "executable_route"
    WITNESS = "witness"
    REFERENCE_ONLY = "reference_only"


class TransportLifecycle(StrEnum):
    DISCOVERED = "DISCOVERED"
    SHADOW = "SHADOW"
    QUALIFIED = "QUALIFIED"
    STANDBY = "STANDBY"
    ACTIVE = "ACTIVE"


@dataclass(frozen=True, slots=True)
class EconomicSource:
    economic_source_id: str
    market_id: str
    venue_id: str
    independence_group_id: str
    authority_class: SourceAuthorityClass

    def __post_init__(self) -> None:
        for name in (
            "economic_source_id",
            "market_id",
            "venue_id",
            "independence_group_id",
        ):
            object.__setattr__(self, name, _required_id(name, getattr(self, name)))


@dataclass(frozen=True, slots=True)
class TransportPath:
    transport_id: str
    provider_id: str
    economic_source_id: str
    adapter_id: str
    adapter_version: str
    lifecycle_state: TransportLifecycle = TransportLifecycle.DISCOVERED

    def __post_init__(self) -> None:
        for name in (
            "transport_id",
            "provider_id",
            "economic_source_id",
            "adapter_id",
            "adapter_version",
        ):
            object.__setattr__(self, name, _required_id(name, getattr(self, name)))


@dataclass(frozen=True, slots=True)
class ExecutionRoute:
    route_id: str
    instrument_id: str
    economic_source_id: str

    def __post_init__(self) -> None:
        for name in ("route_id", "instrument_id", "economic_source_id"):
            object.__setattr__(self, name, _required_id(name, getattr(self, name)))


@dataclass(frozen=True, slots=True)
class RouteAuthorityEvent:
    event_id: str
    route_id: str
    instrument_id: str
    from_economic_source_id: str | None
    to_economic_source_id: str
    initiator: str
    reason: str
    qualification_evidence_refs: tuple[str, ...]
    authorization_signature: str

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "route_id",
            "instrument_id",
            "to_economic_source_id",
            "initiator",
            "reason",
            "authorization_signature",
        ):
            object.__setattr__(self, name, _required_id(name, getattr(self, name)))
        if self.from_economic_source_id is not None:
            object.__setattr__(
                self,
                "from_economic_source_id",
                _required_id("from_economic_source_id", self.from_economic_source_id),
            )
        refs = tuple(
            _required_id("qualification_evidence_ref", value)
            for value in self.qualification_evidence_refs
        )
        if not refs:
            raise ValueError("qualification_evidence_refs are required")
        object.__setattr__(self, "qualification_evidence_refs", refs)


@dataclass(frozen=True, slots=True)
class MarketFabricIdentityRegistry:
    economic_sources: Mapping[str, EconomicSource]
    transports: Mapping[str, TransportPath]
    routes: Mapping[str, ExecutionRoute]

    @classmethod
    def build(
        cls,
        *,
        economic_sources: Iterable[EconomicSource],
        transports: Iterable[TransportPath],
        routes: Iterable[ExecutionRoute] = (),
    ) -> "MarketFabricIdentityRegistry":
        source_map = {row.economic_source_id: row for row in economic_sources}
        transport_map = {row.transport_id: row for row in transports}
        route_map = {row.route_id: row for row in routes}
        if len(source_map) != len(tuple(economic_sources)):
            raise ValueError("duplicate economic_source_id")
        if len(transport_map) != len(tuple(transports)):
            raise ValueError("duplicate transport_id")
        if len(route_map) != len(tuple(routes)):
            raise ValueError("duplicate route_id")
        for row in transport_map.values():
            if row.economic_source_id not in source_map:
                raise ValueError(
                    f"transport {row.transport_id} references unknown economic source"
                )
        for row in route_map.values():
            source = source_map.get(row.economic_source_id)
            if source is None:
                raise ValueError(f"route {row.route_id} references unknown economic source")
            if source.authority_class is not SourceAuthorityClass.EXECUTABLE_ROUTE:
                raise ValueError("execution route must point to executable-route source")
        return cls(
            economic_sources=MappingProxyType(source_map),
            transports=MappingProxyType(transport_map),
            routes=MappingProxyType(route_map),
        )

    def effective_independence_groups(
        self,
        *,
        economic_source_ids: Iterable[str],
    ) -> tuple[str, ...]:
        groups = {
            self.economic_sources[_required_id("economic_source_id", source_id)]
            .independence_group_id
            for source_id in economic_source_ids
        }
        return tuple(sorted(groups))

    def transport_independence_groups(
        self,
        *,
        transport_ids: Iterable[str],
    ) -> tuple[str, ...]:
        source_ids = {
            self.transports[_required_id("transport_id", transport_id)]
            .economic_source_id
            for transport_id in transport_ids
        }
        return self.effective_independence_groups(economic_source_ids=source_ids)

    def apply_route_event(
        self,
        event: RouteAuthorityEvent,
    ) -> "MarketFabricIdentityRegistry":
        target = self.economic_sources.get(event.to_economic_source_id)
        if target is None:
            raise ValueError("route event target economic source is unknown")
        if target.authority_class is not SourceAuthorityClass.EXECUTABLE_ROUTE:
            raise ValueError("route event target is not executable-route qualified")
        current = self.routes.get(event.route_id)
        if current is not None:
            if current.instrument_id != event.instrument_id:
                raise ValueError("route event instrument does not match existing route")
            if current.economic_source_id != event.from_economic_source_id:
                raise ValueError("route event from_economic_source_id mismatch")
        elif event.from_economic_source_id is not None:
            raise ValueError("new route must not claim a prior economic source")

        updated = dict(self.routes)
        updated[event.route_id] = ExecutionRoute(
            route_id=event.route_id,
            instrument_id=event.instrument_id,
            economic_source_id=event.to_economic_source_id,
        )
        return MarketFabricIdentityRegistry(
            economic_sources=self.economic_sources,
            transports=self.transports,
            routes=MappingProxyType(updated),
        )
