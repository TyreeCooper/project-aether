from __future__ import annotations

import pytest

from aether_vnext.market_fabric_provider_lifecycle import (
    ProviderLifecycle,
    ProviderLifecycleRecord,
    QualificationEvidence,
    advance_provider_lifecycle,
    economic_route_change_required,
)


GOOD = QualificationEvidence(
    evidence_id="qual-1",
    fixture_conformance_passed=True,
    live_shadow_passed=True,
    parity_passed=True,
    rights_reviewed=True,
    provenance_complete=True,
    metrics={"freshness_p99_ms": 25.0},
)


def test_provider_progression_requires_shadow_before_qualification() -> None:
    record = ProviderLifecycleRecord(
        transport_id="coinbase-direct",
        economic_source_id="coinbase_exchange",
    )

    with pytest.raises(ValueError, match="invalid provider lifecycle transition"):
        advance_provider_lifecycle(
            record,
            target=ProviderLifecycle.QUALIFIED,
            evidence=GOOD,
        )

    shadow = advance_provider_lifecycle(
        record,
        target=ProviderLifecycle.SHADOW,
        evidence=GOOD,
    )
    assert shadow.state is ProviderLifecycle.SHADOW

    qualified = advance_provider_lifecycle(
        shadow,
        target=ProviderLifecycle.QUALIFIED,
        evidence=GOOD,
    )
    assert qualified.state is ProviderLifecycle.QUALIFIED


def test_qualified_requires_live_shadow_parity_rights_and_provenance() -> None:
    weak = QualificationEvidence(
        evidence_id="qual-weak",
        fixture_conformance_passed=True,
        live_shadow_passed=False,
        parity_passed=True,
        rights_reviewed=True,
        provenance_complete=True,
        metrics={},
    )
    shadow = ProviderLifecycleRecord(
        transport_id="vendor-x",
        economic_source_id="coinbase_exchange",
        state=ProviderLifecycle.SHADOW,
        qualification_evidence_id="fixture-only",
    )

    with pytest.raises(ValueError, match="live_shadow_passed"):
        advance_provider_lifecycle(
            shadow,
            target=ProviderLifecycle.QUALIFIED,
            evidence=weak,
        )


def test_active_requires_explicit_activation_event() -> None:
    qualified = ProviderLifecycleRecord(
        transport_id="vendor-x",
        economic_source_id="coinbase_exchange",
        state=ProviderLifecycle.QUALIFIED,
        qualification_evidence_id="qual-1",
    )

    with pytest.raises(ValueError, match="activation_event_id"):
        advance_provider_lifecycle(
            qualified,
            target=ProviderLifecycle.ACTIVE,
            evidence=GOOD,
        )

    active = advance_provider_lifecycle(
        qualified,
        target=ProviderLifecycle.ACTIVE,
        evidence=GOOD,
        activation_event_id="transport-activation-1",
    )
    assert active.state is ProviderLifecycle.ACTIVE


def test_transport_swap_same_economic_source_does_not_imply_route_change() -> None:
    before = ProviderLifecycleRecord(
        transport_id="coinbase-direct",
        economic_source_id="coinbase_exchange",
        state=ProviderLifecycle.ACTIVE,
        qualification_evidence_id="qual-1",
        activation_event_id="activation-1",
    )
    after = ProviderLifecycleRecord(
        transport_id="vendor-x-coinbase",
        economic_source_id="coinbase_exchange",
        state=ProviderLifecycle.ACTIVE,
        qualification_evidence_id="qual-2",
        activation_event_id="activation-2",
    )

    assert economic_route_change_required(before, after) is False
