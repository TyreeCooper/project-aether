"""No-fabrication runtime-binding worklist for AETHER vNext.

The worklist projects canonical repository facts and identifies unresolved external
facts for each seed asset. It is deliberately not a runnable manifest: unknown
provider/account values remain None until reviewed from real provider sessions.
"""
from __future__ import annotations

from aether_vnext.calendar_sources import (
    IMPLEMENTED_CALENDAR_PROVIDERS,
    calendar_requires_external_provider,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.market_sources import (
    IMPLEMENTED_MARKET_SOURCES,
    PENDING_MARKET_SOURCES,
)
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.shortability_sources import (
    IMPLEMENTED_SHORTABILITY_PROVIDERS,
)


_BINDING_FIELDS = (
    "asset_id",
    "broker_symbol",
    "primary_market_source_id",
    "fallback_market_source_id",
    "stale_threshold_ms",
    "calendar_provider_id",
    "calendar_market_id",
    "current_contract",
    "market_data_contract_id",
    "expiry_utc",
    "next_contract",
    "shortability_provider_id",
    "shortability_stale_threshold_ms",
    "source_ref",
)


def binding_template(asset_id: str) -> dict[str, object]:
    row = SEED_REGISTRY[str(asset_id).strip().lower()]
    payload = {field: None for field in _BINDING_FIELDS}
    payload["asset_id"] = row.asset_id
    payload["broker_symbol"] = row.broker_symbol
    payload["primary_market_source_id"] = row.primary_market_source_id
    return payload


def required_external_fields(asset_id: str) -> tuple[str, ...]:
    row = SEED_REGISTRY[str(asset_id).strip().lower()]
    template = binding_template(row.asset_id)
    fields: list[str] = []

    if template["broker_symbol"] is None:
        fields.append("broker_symbol")
    if template["primary_market_source_id"] is None:
        fields.append("primary_market_source_id")

    # Frozen source intentionally leaves freshness numeric policy unbound.
    fields.append("stale_threshold_ms")

    if calendar_requires_external_provider(row.calendar_id):
        fields.extend(("calendar_provider_id", "calendar_market_id"))

    if row.futures_lifecycle is not None:
        fields.extend(
            (
                "current_contract",
                "market_data_contract_id",
                "expiry_utc",
                "next_contract",
            )
        )

    if row.borrow_required:
        if "market_data_contract_id" not in fields:
            fields.append("market_data_contract_id")
        fields.extend(
            (
                "shortability_provider_id",
                "shortability_stale_threshold_ms",
            )
        )

    return tuple(fields)


def _market_candidates(asset_id: str) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for source_id, capability in sorted(IMPLEMENTED_MARKET_SOURCES.items()):
        if capability.supports_asset(asset_id):
            rows.append(
                {
                    "source_id": source_id,
                    "implemented": True,
                    "market_print_implemented": bool(
                        capability.market_print_transport_id
                        and capability.market_print_parser_version
                    ),
                }
            )
    for source_id, capability in sorted(PENDING_MARKET_SOURCES.items()):
        if capability.supports_asset(asset_id):
            rows.append(
                {
                    "source_id": source_id,
                    "implemented": False,
                    "market_print_implemented": False,
                }
            )
    return tuple(rows)


def _calendar_candidates(calendar_id: str) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for provider_id, capability in sorted(
        IMPLEMENTED_CALENDAR_PROVIDERS.items()
    ):
        if capability.supports_calendar(calendar_id):
            rows.append(
                {
                    "provider_id": provider_id,
                    "requires_market_id": capability.requires_market_id,
                }
            )
    return tuple(rows)


def _shortability_candidates(asset_id: str) -> tuple[str, ...]:
    return tuple(
        provider_id
        for provider_id, capability in sorted(
            IMPLEMENTED_SHORTABILITY_PROVIDERS.items()
        )
        if capability.supports_asset(asset_id)
    )


def runtime_binding_worklist() -> dict[str, object]:
    assets: list[dict[str, object]] = []
    templates: list[dict[str, object]] = []

    for asset_id in sorted(SEED_REGISTRY):
        row = SEED_REGISTRY[asset_id]
        templates.append(binding_template(asset_id))
        assets.append(
            {
                "asset_id": asset_id,
                "canonical_symbol": row.canonical_symbol,
                "broker": row.broker,
                "calendar_id": row.calendar_id,
                "template": binding_template(asset_id),
                "required_external_fields": list(
                    required_external_fields(asset_id)
                ),
                "market_source_candidates": list(
                    _market_candidates(asset_id)
                ),
                "calendar_provider_candidates": list(
                    _calendar_candidates(row.calendar_id)
                ),
                "shortability_provider_candidates": list(
                    _shortability_candidates(asset_id)
                ),
            }
        )

    return {
        "configuration_hash": CONFIGURATION_HASH,
        "expected_asset_ids": sorted(SEED_REGISTRY),
        "binding_count": len(assets),
        "ready_for_strict_import": False,
        "bindings": templates,
        "assets": assets,
    }
