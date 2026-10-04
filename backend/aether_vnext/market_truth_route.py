"""Layer 3: human-controlled executable Route authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json

from aether_vnext.market_truth_contract import FIRST_PROOF_MAX_EXECUTABLE_ROUTES
from aether_vnext.market_truth_provider import ProviderCardRegistry
from aether_vnext.market_truth_universe import AssetUniverse


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class RouteRecord:
    canonical_instrument_id: str
    executable_provider_id: str
    witness_provider_ids: tuple[str, ...]
    human_set_by: str
    human_set_at_utc: datetime
    route_revision: int

    def __post_init__(self) -> None:
        if not self.canonical_instrument_id.strip():
            raise ValueError("canonical_instrument_id is required")
        if not self.executable_provider_id.strip():
            raise ValueError("executable_provider_id is required")
        if not self.human_set_by.strip():
            raise ValueError("human_set_by is required")
        if self.human_set_at_utc.tzinfo is None:
            raise ValueError("human_set_at_utc must be timezone-aware")
        if self.route_revision < 1:
            raise ValueError("route_revision must be >= 1")
        normalized = tuple(str(x).strip().lower() for x in self.witness_provider_ids)
        if any(not value for value in normalized):
            raise ValueError("witness provider ids must be nonblank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate witness provider")
        if self.executable_provider_id.strip().lower() in set(normalized):
            raise ValueError("executable provider cannot also be a witness")

    @property
    def route_id(self) -> str:
        payload = {
            "instrument": self.canonical_instrument_id.strip().lower(),
            "executable_provider": self.executable_provider_id.strip().lower(),
            "witnesses": sorted(x.strip().lower() for x in self.witness_provider_ids),
            "revision": self.route_revision,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        return f"route:{payload['instrument']}:{digest}"


class HumanRouteRegistry:
    """Route authority. Transport identity is deliberately absent from this layer."""

    def __init__(
        self,
        *,
        universe: AssetUniverse,
        providers: ProviderCardRegistry,
        routes: tuple[RouteRecord, ...] = (),
        first_proof_evidence_id: str | None = None,
    ) -> None:
        self._universe = universe
        self._providers = providers
        self._routes: dict[str, RouteRecord] = {}
        self._first_proof_evidence_id = (
            None
            if first_proof_evidence_id is None
            else str(first_proof_evidence_id).strip() or None
        )
        for route in routes:
            self._validate_route(route, replacing=False)
            self._routes[route.canonical_instrument_id.strip().lower()] = route

    @property
    def first_proof_passed(self) -> bool:
        return self._first_proof_evidence_id is not None

    @property
    def first_proof_evidence_id(self) -> str | None:
        return self._first_proof_evidence_id

    def _validate_route(self, route: RouteRecord, *, replacing: bool) -> None:
        instrument_id = route.canonical_instrument_id.strip().lower()
        if self._universe.get(instrument_id) is None:
            raise KeyError(f"route instrument not in Asset Universe: {instrument_id}")
        executable = self._providers.require(route.executable_provider_id)
        if not executable.can_execute:
            raise ValueError("executable provider lacks execute capability")
        for provider_id in route.witness_provider_ids:
            witness = self._providers.require(provider_id)
            if not witness.can_observe:
                raise ValueError(f"witness provider lacks observe capability: {provider_id}")

        new_key = instrument_id not in self._routes
        projected_count = len(self._routes) + (1 if new_key else 0)
        if (
            not self.first_proof_passed
            and projected_count > FIRST_PROOF_MAX_EXECUTABLE_ROUTES
        ):
            raise RuntimeError(
                "first proof gate blocks a second executable route"
            )
        if replacing and instrument_id not in self._routes:
            raise KeyError(f"cannot replace missing route: {instrument_id}")

    def add_human_route(self, route: RouteRecord) -> None:
        key = route.canonical_instrument_id.strip().lower()
        if key in self._routes:
            raise ValueError(f"route already exists: {key}")
        self._validate_route(route, replacing=False)
        self._routes[key] = route

    def replace_human_route(
        self,
        instrument_id: str,
        *,
        executable_provider_id: str,
        witness_provider_ids: tuple[str, ...],
        human_set_by: str,
        human_set_at_utc: datetime,
    ) -> RouteRecord:
        key = str(instrument_id).strip().lower()
        prior = self._routes.get(key)
        if prior is None:
            raise KeyError(f"cannot replace missing route: {key}")
        candidate = RouteRecord(
            canonical_instrument_id=prior.canonical_instrument_id,
            executable_provider_id=executable_provider_id,
            witness_provider_ids=witness_provider_ids,
            human_set_by=human_set_by,
            human_set_at_utc=human_set_at_utc,
            route_revision=prior.route_revision + 1,
        )
        self._validate_route(candidate, replacing=True)
        self._routes[key] = candidate
        return candidate

    def mark_first_proof_passed(self, *, proof_evidence_id: str) -> None:
        value = str(proof_evidence_id).strip()
        if not value:
            raise ValueError("proof_evidence_id is required")
        self._first_proof_evidence_id = value

    def get(self, instrument_id: str) -> RouteRecord | None:
        return self._routes.get(str(instrument_id).strip().lower())

    def routes(self) -> tuple[RouteRecord, ...]:
        return tuple(self._routes[key] for key in sorted(self._routes))


def same_route_transport_failover(route: RouteRecord, *, provider_id: str, venue: str, providers: ProviderCardRegistry) -> bool:
    """True only when a transport failover preserves the human-selected provider/venue."""
    selected = providers.require(route.executable_provider_id)
    return (
        str(provider_id).strip().lower()
        == route.executable_provider_id.strip().lower()
        and str(venue).strip().lower() == selected.venue.strip().lower()
    )
