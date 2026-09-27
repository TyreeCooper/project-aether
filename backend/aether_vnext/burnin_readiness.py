"""Read-only burn-in readiness aggregation for AETHER vNext.

This module does not provision infrastructure, mutate the book, fabricate provider
bindings, create evidence, or start a campaign. It converts exact repository/book
facts into one deterministic readiness report so operators can distinguish internal
implementation defects from external configuration and empirical-evidence blockers.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from aether_vnext.db_isolation import DatabaseIsolationResult
from aether_vnext.forward_paper_preflight import ForwardPaperPreflightResult
from aether_vnext.registry import SEED_REGISTRY


@dataclass(frozen=True, slots=True)
class BurninReadiness:
    ready: bool
    database_isolated: bool
    vnext_schema_exists: bool
    schema_complete: bool
    runtime_binding_universe_complete: bool
    canonical_preflight_startable: bool
    expected_asset_ids: tuple[str, ...]
    runtime_binding_asset_ids: tuple[str, ...]
    missing_runtime_binding_assets: tuple[str, ...]
    missing_schema_tables: tuple[str, ...]
    blocker_counts: tuple[tuple[str, int], ...]
    blocker_classes: tuple[tuple[str, int], ...]


def blocker_class(code: str) -> str:
    """Classify a concrete blocker without weakening or rewriting it."""
    value = str(code).strip()
    if not value:
        return "internal_contract"

    if value == "one_or_more_routes_not_startable":
        return "aggregate"

    if value in {
        "paper_only_not_enabled",
        "live_not_blocked",
        "forced_strategy_entries_enabled",
    }:
        return "safety_invariant"

    if value in {
        "canonical_policy_snapshot_missing",
        "runtime_product_binding_missing",
        "runtime_product_binding_configuration_mismatch",
    }:
        return "environment_initialization"

    if (
        value == "stale_order_intents_present"
        or value.startswith("risk_admission_reconciliation:")
    ):
        return "runtime_reconciliation"


    if (
        "provider_spec_pending" in value
        or value.startswith("tastyfx_fix_")
    ):
        return "external_provider_spec"

    if value in {
        "runtime_broker_symbol_missing",
        "market_data_source_missing",
        "stale_threshold_missing",
        "calendar_provider_missing",
        "calendar_provider_market_id_missing",
        "current_futures_contract_missing",
        "futures_expiry_missing",
        "next_futures_contract_missing",
        "market_data_contract_id_missing",
        "shortability_provider_missing",
        "shortability_stale_threshold_missing",
        "futures_contract_in_roll_cutoff",
    }:
        return "external_runtime_configuration"

    if value == "forward_paper_ledger:campaign_safety_invariant_mismatch":
        return "safety_invariant"

    if value in {
        "forward_paper_ledger:campaign_policy_snapshot_missing",
        "forward_paper_ledger:campaign_policy_snapshot_mismatch",
    }:
        return "environment_initialization"

    if value.startswith("forward_paper_ledger:runtime_binding_"):
        return "external_runtime_configuration"

    if value.startswith("forward_paper_ledger:"):
        return "empirical_evidence"

    if value in {
        "missing_current_held_out_baseline",
        "held_out_baseline_lacks_research_provenance",
        "held_out_window_reload_failed",
    }:
        return "empirical_evidence"

    if value in {
        "exit_contract_incomplete",
        "exit_contract_missing",
    }:
        return "source_authority"

    return "internal_contract"


def _route_blockers(
    preflight: ForwardPaperPreflightResult | None,
) -> tuple[str, ...]:
    if preflight is None:
        return ()
    values: list[str] = list(preflight.blockers)
    for row in preflight.route_results:
        values.extend(row.blockers)
    return tuple(values)


def build_burnin_readiness(
    *,
    isolation: DatabaseIsolationResult,
    expected_schema_tables: Iterable[str],
    actual_schema_tables: Iterable[str],
    runtime_binding_asset_ids: Iterable[str],
    preflight: ForwardPaperPreflightResult | None,
    extra_blockers: Iterable[str] = (),
) -> BurninReadiness:
    expected_assets = tuple(sorted(SEED_REGISTRY))
    runtime_assets = tuple(
        sorted({str(asset).strip().lower() for asset in runtime_binding_asset_ids})
    )
    missing_assets = tuple(
        sorted(set(expected_assets) - set(runtime_assets))
    )

    expected_tables = {str(name).strip() for name in expected_schema_tables}
    actual_tables = {str(name).strip() for name in actual_schema_tables}
    missing_tables = tuple(sorted(expected_tables - actual_tables))

    blockers = list(_route_blockers(preflight))
    blockers.extend(str(code).strip() for code in extra_blockers if str(code).strip())
    counts = Counter(blockers)
    classes = Counter()
    for code, count in counts.items():
        classes[blocker_class(code)] += count

    schema_complete = isolation.vnext_schema_exists and not missing_tables
    runtime_complete = not missing_assets and len(runtime_assets) == len(expected_assets)
    preflight_startable = bool(preflight is not None and preflight.startable)

    ready = bool(
        isolation.isolated
        and schema_complete
        and runtime_complete
        and preflight_startable
        and not tuple(extra_blockers)
    )
    return BurninReadiness(
        ready=ready,
        database_isolated=isolation.isolated,
        vnext_schema_exists=isolation.vnext_schema_exists,
        schema_complete=schema_complete,
        runtime_binding_universe_complete=runtime_complete,
        canonical_preflight_startable=preflight_startable,
        expected_asset_ids=expected_assets,
        runtime_binding_asset_ids=runtime_assets,
        missing_runtime_binding_assets=missing_assets,
        missing_schema_tables=missing_tables,
        blocker_counts=tuple(sorted(counts.items())),
        blocker_classes=tuple(sorted(classes.items())),
    )


def readiness_payload(readiness: BurninReadiness) -> dict[str, object]:
    return {
        "ready": readiness.ready,
        "database_isolated": readiness.database_isolated,
        "vnext_schema_exists": readiness.vnext_schema_exists,
        "schema_complete": readiness.schema_complete,
        "runtime_binding_universe_complete": (
            readiness.runtime_binding_universe_complete
        ),
        "canonical_preflight_startable": (
            readiness.canonical_preflight_startable
        ),
        "expected_asset_ids": list(readiness.expected_asset_ids),
        "runtime_binding_asset_ids": list(
            readiness.runtime_binding_asset_ids
        ),
        "missing_runtime_binding_assets": list(
            readiness.missing_runtime_binding_assets
        ),
        "missing_schema_tables": list(readiness.missing_schema_tables),
        "blocker_counts": {
            code: count for code, count in readiness.blocker_counts
        },
        "blocker_classes": {
            category: count
            for category, count in readiness.blocker_classes
        },
    }
