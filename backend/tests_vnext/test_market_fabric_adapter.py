from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

import pytest

from aether_vnext.market_fabric_adapter import (
    AdapterContractExpectation,
    lifecycle_after_fixture_conformance,
    lifecycle_after_shadow_qualification,
    prove_provider_swap,
    run_adapter_conformance,
)
from aether_vnext.market_fabric_identity import TransportLifecycle
from aether_vnext.market_fabric_observation import (
    CanonicalMarketObservation,
    ObservationType,
    payload_sha256,
)


UTC = timezone.utc


class FixtureAdapter:
    def __init__(
        self,
        *,
        provider_id: str,
        transport_id: str,
        adapter_id: str,
    ) -> None:
        self.provider_id = provider_id
        self.transport_id = transport_id
        self.adapter_id = adapter_id
        self.adapter_version = "v1"
        self.economic_source_id = "coinbase_exchange"

    def capabilities(self) -> frozenset[str]:
        return frozenset({"quotes", "field_presence", "raw_provenance"})

    def normalize_fixture(
        self,
        payload: Mapping[str, object],
    ) -> CanonicalMarketObservation:
        bid = float(payload["bid"])
        ask = float(payload["ask"])
        raw = f"{bid}|{ask}".encode()
        return CanonicalMarketObservation(
            event_id=f"evt:{self.adapter_id}",
            market_id="crypto_spot_usd",
            asset_id="btc",
            instrument_id="btc_usd",
            venue_id="coinbase",
            economic_source_id=self.economic_source_id,
            independence_group_id="venue:coinbase",
            provider_id=self.provider_id,
            transport_id=self.transport_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            observation_type=ObservationType.QUOTE,
            field_presence=frozenset({"bid", "ask"}),
            bid=bid,
            ask=ask,
            last=None,
            bid_size=None,
            ask_size=None,
            exchange_ts=datetime(2026, 10, 4, 1, 0, tzinfo=UTC),
            vendor_ts=None,
            receive_ts=datetime(2026, 10, 4, 1, 0, 1, tzinfo=UTC),
            native_sequence="42",
            native_event_id="book-42",
            raw_payload_hash=payload_sha256(raw),
            raw_payload_ref=f"fixture://{self.adapter_id}",
        )


EXPECTATION = AdapterContractExpectation(
    economic_source_id="coinbase_exchange",
    market_id="crypto_spot_usd",
    instrument_id="btc_usd",
    venue_id="coinbase",
    observation_type="quote",
    required_capabilities=frozenset({"quotes", "field_presence"}),
    required_field_presence=frozenset({"bid", "ask"}),
)


def test_adapter_must_pass_fixture_conformance_before_shadow() -> None:
    adapter = FixtureAdapter(
        provider_id="coinbase_direct",
        transport_id="coinbase_ws",
        adapter_id="aether.adapter.coinbase.ws",
    )
    report = run_adapter_conformance(
        adapter,
        fixture_payload={"bid": 100.0, "ask": 101.0},
        expectation=EXPECTATION,
    )

    assert report.passed is True
    assert lifecycle_after_fixture_conformance(report) is TransportLifecycle.SHADOW
    with pytest.raises(ValueError, match="live shadow evidence"):
        lifecycle_after_shadow_qualification(
            report,
            live_shadow_evidence_passed=False,
        )


def test_provider_swap_preserves_canonical_semantics_except_provenance() -> None:
    direct = FixtureAdapter(
        provider_id="coinbase_direct",
        transport_id="coinbase_ws",
        adapter_id="aether.adapter.coinbase.ws",
    )
    vendor = FixtureAdapter(
        provider_id="vendor_x",
        transport_id="vendor_x_coinbase",
        adapter_id="aether.adapter.vendor_x.coinbase",
    )
    fixture = {"bid": 100.0, "ask": 101.0}

    before = direct.normalize_fixture(fixture)
    after = vendor.normalize_fixture(fixture)
    passed, errors = prove_provider_swap(before, after)

    assert passed is True
    assert errors == ()
    assert before.provider_id != after.provider_id
    assert before.transport_id != after.transport_id
    assert before.economic_source_id == after.economic_source_id


def test_conformance_fails_when_adapter_leaks_wrong_economic_identity() -> None:
    adapter = FixtureAdapter(
        provider_id="vendor_y",
        transport_id="vendor_y_coinbase",
        adapter_id="aether.adapter.vendor_y.coinbase",
    )
    adapter.economic_source_id = "wrong_source"

    report = run_adapter_conformance(
        adapter,
        fixture_payload={"bid": 100.0, "ask": 101.0},
        expectation=EXPECTATION,
    )

    assert report.passed is False
    assert "adapter_economic_source_mismatch" in report.errors
    with pytest.raises(ValueError, match="fixture conformance"):
        lifecycle_after_fixture_conformance(report)
