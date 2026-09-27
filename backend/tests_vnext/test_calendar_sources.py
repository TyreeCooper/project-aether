from __future__ import annotations

from aether_vnext.calendar_sources import (
    IMPLEMENTED_CALENDAR_PROVIDERS,
    calendar_provider_implementation_blockers,
)
from aether_vnext.registry_runtime import RuntimeRegistryBinding, binding_blockers


def test_noncrypto_calendar_provider_registry_is_intentionally_empty() -> None:
    assert dict(IMPLEMENTED_CALENDAR_PROVIDERS) == {}


def test_crypto_24x7_needs_no_external_calendar_provider() -> None:
    assert calendar_provider_implementation_blockers(
        calendar_id="crypto_24x7",
        provider_id=None,
    ) == ()


def test_named_noncrypto_provider_is_not_mistaken_for_implemented_code() -> None:
    assert calendar_provider_implementation_blockers(
        calendar_id="us_fut_idx",
        provider_id="reviewed.calendar",
    ) == ("calendar_provider_implementation_missing",)


def test_strict_runtime_binding_requires_calendar_provider_implementation() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="eurusd",
        broker_symbol="EUR/USD",
        primary_market_source_id="reviewed.fx.source",
        stale_threshold_ms=1500,
        calendar_provider_id="reviewed.calendar",
        source_ref="test",
    )

    assert "calendar_provider_implementation_missing" in binding_blockers(
        binding,
        require_calendar_provider_implementation=True,
    )
    assert "calendar_provider_implementation_missing" not in binding_blockers(
        binding,
        require_calendar_provider_implementation=False,
    )
