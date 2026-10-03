"""No-fabrication provider commissioning report for AETHER vNext.

This report turns the canonical runtime-binding worklist into a provider-oriented
handoff for the eventual authenticated commissioning pass. It deliberately records
no credential values and makes no claim about whether an operator has an account.
"""
from __future__ import annotations

from collections import defaultdict

from aether_vnext.runtime_binding_worklist import runtime_binding_worklist


def provider_commissioning_readiness() -> dict[str, object]:
    worklist = runtime_binding_worklist()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)

    for row in worklist["assets"]:
        broker = str(row["broker"]).strip()
        groups[broker].append(row)

    providers: list[dict[str, object]] = []
    for broker in sorted(groups):
        rows = sorted(groups[broker], key=lambda item: str(item["asset_id"]))
        unresolved: set[str] = set()
        market_sources: dict[str, dict[str, object]] = {}
        calendar_providers: dict[str, dict[str, object]] = {}
        shortability_providers: set[str] = set()

        for row in rows:
            unresolved.update(str(value) for value in row["required_external_fields"])
            for candidate in row["market_source_candidates"]:
                source_id = str(candidate["source_id"])
                market_sources[source_id] = {
                    "source_id": source_id,
                    "implemented": bool(candidate["implemented"]),
                    "market_print_implemented": bool(
                        candidate["market_print_implemented"]
                    ),
                }
            for candidate in row["calendar_provider_candidates"]:
                provider_id = str(candidate["provider_id"])
                calendar_providers[provider_id] = {
                    "provider_id": provider_id,
                    "requires_market_id": bool(candidate["requires_market_id"]),
                }
            shortability_providers.update(
                str(value) for value in row["shortability_provider_candidates"]
            )

        market_rows = [
            market_sources[key] for key in sorted(market_sources)
        ]
        providers.append(
            {
                "provider": broker,
                "account_state": "not_observed",
                "asset_ids": [str(row["asset_id"]) for row in rows],
                "unresolved_external_fields": sorted(unresolved),
                "market_source_candidates": market_rows,
                "calendar_provider_candidates": [
                    calendar_providers[key]
                    for key in sorted(calendar_providers)
                ],
                "shortability_provider_candidates": sorted(
                    shortability_providers
                ),
                "provider_spec_pending": any(
                    not row["implemented"] for row in market_rows
                ),
            }
        )

    return {
        "configuration_hash": worklist["configuration_hash"],
        "expected_asset_ids": worklist["expected_asset_ids"],
        "binding_count": worklist["binding_count"],
        "strict_import_ready": False,
        "credential_values_present": False,
        "account_state_source": "not_observed",
        "providers": providers,
    }
