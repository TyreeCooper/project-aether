"""MF-05e provider adapter conformance and swap-proof contracts.

Provider-specific behavior terminates at the adapter boundary. Adapters may enter
SHADOW only after deterministic fixture conformance; QUALIFIED additionally requires
live shadow evidence. Downstream semantics are compared without provider-specific
provenance fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from aether_vnext.market_fabric_identity import TransportLifecycle
from aether_vnext.market_fabric_observation import CanonicalMarketObservation


class MarketDataAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    provider_id: str
    transport_id: str
    economic_source_id: str

    def capabilities(self) -> frozenset[str]: ...

    def normalize_fixture(
        self,
        payload: Mapping[str, object],
    ) -> CanonicalMarketObservation: ...


@dataclass(frozen=True, slots=True)
class AdapterContractExpectation:
    economic_source_id: str
    market_id: str
    instrument_id: str
    venue_id: str
    observation_type: str
    required_capabilities: frozenset[str]
    required_field_presence: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdapterConformanceReport:
    adapter_id: str
    adapter_version: str
    provider_id: str
    transport_id: str
    economic_source_id: str
    passed: bool
    errors: tuple[str, ...]

    @property
    def may_enter_shadow(self) -> bool:
        return self.passed


def canonical_semantic_projection(
    observation: CanonicalMarketObservation,
) -> dict[str, object]:
    """Downstream meaning with delivery/provenance identity intentionally excluded."""
    return {
        "market_id": observation.market_id,
        "asset_id": observation.asset_id,
        "instrument_id": observation.instrument_id,
        "venue_id": observation.venue_id,
        "economic_source_id": observation.economic_source_id,
        "independence_group_id": observation.independence_group_id,
        "observation_type": observation.observation_type.value,
        "field_presence": tuple(sorted(observation.field_presence)),
        "bid": observation.bid,
        "ask": observation.ask,
        "last": observation.last,
        "bid_size": observation.bid_size,
        "ask_size": observation.ask_size,
        "exchange_ts": (
            None if observation.exchange_ts is None else observation.exchange_ts.isoformat()
        ),
        "vendor_ts": (
            None if observation.vendor_ts is None else observation.vendor_ts.isoformat()
        ),
        "native_sequence": observation.native_sequence,
        "native_event_id": observation.native_event_id,
        "schema_version": observation.schema_version,
    }


def run_adapter_conformance(
    adapter: MarketDataAdapter,
    *,
    fixture_payload: Mapping[str, object],
    expectation: AdapterContractExpectation,
) -> AdapterConformanceReport:
    errors: list[str] = []
    capabilities = adapter.capabilities()
    missing_capabilities = expectation.required_capabilities - capabilities
    if missing_capabilities:
        errors.append(
            "missing_capabilities:" + ",".join(sorted(missing_capabilities))
        )
    if adapter.economic_source_id != expectation.economic_source_id:
        errors.append("adapter_economic_source_mismatch")

    try:
        observation = adapter.normalize_fixture(fixture_payload)
    except Exception as exc:
        errors.append(f"normalize_error:{type(exc).__name__}:{exc}")
    else:
        if observation.economic_source_id != expectation.economic_source_id:
            errors.append("observation_economic_source_mismatch")
        if observation.market_id != expectation.market_id:
            errors.append("market_id_mismatch")
        if observation.instrument_id != expectation.instrument_id:
            errors.append("instrument_id_mismatch")
        if observation.venue_id != expectation.venue_id:
            errors.append("venue_id_mismatch")
        if observation.observation_type.value != expectation.observation_type:
            errors.append("observation_type_mismatch")
        missing_fields = (
            expectation.required_field_presence - observation.field_presence
        )
        if missing_fields:
            errors.append(
                "missing_field_presence:" + ",".join(sorted(missing_fields))
            )
        if observation.provider_id != adapter.provider_id:
            errors.append("provider_provenance_mismatch")
        if observation.transport_id != adapter.transport_id:
            errors.append("transport_provenance_mismatch")
        if observation.adapter_id != adapter.adapter_id:
            errors.append("adapter_provenance_mismatch")
        if observation.adapter_version != adapter.adapter_version:
            errors.append("adapter_version_mismatch")

    return AdapterConformanceReport(
        adapter_id=str(adapter.adapter_id),
        adapter_version=str(adapter.adapter_version),
        provider_id=str(adapter.provider_id),
        transport_id=str(adapter.transport_id),
        economic_source_id=str(adapter.economic_source_id),
        passed=not errors,
        errors=tuple(errors),
    )


def prove_provider_swap(
    before: CanonicalMarketObservation,
    after: CanonicalMarketObservation,
) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    if before.economic_source_id != after.economic_source_id:
        errors.append("economic_source_changed")
    if canonical_semantic_projection(before) != canonical_semantic_projection(after):
        errors.append("canonical_semantics_changed")
    if (
        before.provider_id == after.provider_id
        and before.transport_id == after.transport_id
        and before.adapter_id == after.adapter_id
    ):
        errors.append("provider_transport_adapter_not_replaced")
    return (not errors, tuple(errors))


def lifecycle_after_fixture_conformance(
    report: AdapterConformanceReport,
) -> TransportLifecycle:
    if not report.passed:
        raise ValueError("adapter cannot enter SHADOW without fixture conformance")
    return TransportLifecycle.SHADOW


def lifecycle_after_shadow_qualification(
    report: AdapterConformanceReport,
    *,
    live_shadow_evidence_passed: bool,
) -> TransportLifecycle:
    if not report.passed:
        raise ValueError("adapter fixture conformance failed")
    if not live_shadow_evidence_passed:
        raise ValueError("live shadow evidence is required for QUALIFIED")
    return TransportLifecycle.QUALIFIED
