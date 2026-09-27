"""Test support for durable runtime Product Registry bindings."""
from __future__ import annotations

from datetime import datetime, timedelta

from aether_vnext.registry import registry_row
from aether_vnext.registry_runtime import RuntimeRegistryBinding, binding_hash


def test_runtime_binding(
    asset_id: str,
    *,
    now: datetime,
) -> RuntimeRegistryBinding:
    asset = str(asset_id).strip().lower()
    base = registry_row(asset)
    is_futures = base.futures_lifecycle is not None
    is_equity_borrow = base.borrow_required

    contract = None
    next_contract = None
    expiry = None
    if is_futures:
        contract = f"{base.canonical_symbol}TEST1"
        next_contract = f"{base.canonical_symbol}TEST2"
        expiry = now + timedelta(days=90)

    return RuntimeRegistryBinding(
        asset_id=asset,
        broker_symbol=contract or base.canonical_symbol,
        primary_market_source_id=f"test.market.{asset}",
        fallback_market_source_id=None,
        stale_threshold_ms=1500,
        calendar_provider_id=(
            None if base.calendar_id == "crypto_24x7" else "test.calendar"
        ),
        current_contract=contract,
        expiry_utc=expiry,
        next_contract=next_contract,
        shortability_provider_id=(
            "test.shortability" if is_equity_borrow else None
        ),
        source_ref="test-fixture",
    )


def record_test_runtime_binding(
    conn,
    store,
    *,
    asset_id: str,
    configuration_hash: str,
    now: datetime,
    registry_version: str = "test-runtime-registry-v1",
) -> str:
    binding = test_runtime_binding(asset_id, now=now)
    return store.upsert_runtime_registry_binding(
        conn,
        binding,
        registry_version=registry_version,
        configuration_hash=configuration_hash,
        updated_at_utc=now,
    )


def test_runtime_binding_hash(asset_id: str, *, now: datetime) -> str:
    return binding_hash(test_runtime_binding(asset_id, now=now))
