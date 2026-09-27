from __future__ import annotations

from aether_vnext.burnin_readiness import (
    blocker_class,
    build_burnin_readiness,
    readiness_payload,
)
from aether_vnext.db_isolation import DatabaseIsolationResult
from aether_vnext.forward_paper_preflight import (
    ForwardPaperPreflightResult,
    ForwardPaperRoutePreflight,
    ForwardPaperRouteRequest,
)
from aether_vnext.registry import SEED_REGISTRY


def _isolation(*, isolated: bool = True, schema: bool = True):
    return DatabaseIsolationResult(
        database_name="aether_vnext_burnin",
        legacy_tables_found=() if isolated else ("aether_order",),
        vnext_schema_exists=schema,
        isolated=isolated,
    )


def _preflight(
    *,
    startable: bool,
    route_blockers: tuple[str, ...] = (),
) -> ForwardPaperPreflightResult:
    route = ForwardPaperRoutePreflight(
        request=ForwardPaperRouteRequest(
            route_id="eurusd:intraday:long",
            playbook_id="pb_fx_break_v1_3",
        ),
        eligible=not route_blockers,
        playbook_version="1.3",
        held_out_window_ids=("heldout-1",) if not route_blockers else (),
        held_out_window_count=1 if not route_blockers else 0,
        independent_held_out_n=1 if not route_blockers else 0,
        runtime_registry_binding_hash=("binding" if not route_blockers else None),
        route_baseline_hash=("route-hash" if not route_blockers else None),
        campaign_route_id=("campaign-route" if not route_blockers else None),
        blockers=route_blockers,
    )
    return ForwardPaperPreflightResult(
        campaign_id="campaign-1",
        configuration_hash="cfg",
        policy_version="policy-v1",
        requested_route_count=1,
        startable=startable,
        route_results=(route,),
        baseline_snapshot_hash=("baseline" if startable else None),
        blockers=() if startable else ("one_or_more_routes_not_startable",),
    )


def test_readiness_is_green_only_when_all_layers_are_green() -> None:
    expected_tables = {"policy_snapshots", "product_registry_state"}
    result = build_burnin_readiness(
        isolation=_isolation(),
        expected_schema_tables=expected_tables,
        actual_schema_tables=expected_tables,
        runtime_binding_asset_ids=tuple(SEED_REGISTRY),
        preflight=_preflight(startable=True),
    )
    assert result.ready is True
    payload = readiness_payload(result)
    assert payload["runtime_binding_universe_complete"] is True
    assert payload["missing_runtime_binding_assets"] == []
    assert payload["blocker_counts"] == {}


def test_readiness_exposes_schema_binding_provider_and_evidence_blockers() -> None:
    assets = tuple(asset for asset in SEED_REGISTRY if asset != "usdjpy")
    result = build_burnin_readiness(
        isolation=_isolation(),
        expected_schema_tables={"policy_snapshots", "product_registry_state"},
        actual_schema_tables={"policy_snapshots"},
        runtime_binding_asset_ids=assets,
        preflight=_preflight(
            startable=False,
            route_blockers=(
                "primary_market_source_provider_spec_pending",
                "missing_current_held_out_baseline",
            ),
        ),
        extra_blockers=("vnext_schema_incomplete",),
    )
    assert result.ready is False
    assert result.missing_runtime_binding_assets == ("usdjpy",)
    assert result.missing_schema_tables == ("product_registry_state",)
    payload = readiness_payload(result)
    assert payload["blocker_classes"]["external_provider_spec"] == 1
    assert payload["blocker_classes"]["empirical_evidence"] == 1
    assert payload["blocker_classes"]["internal_contract"] == 1


def test_blocker_classification_keeps_exact_external_and_safety_boundaries() -> None:
    assert blocker_class(
        "primary_market_source_provider_spec_pending"
    ) == "external_provider_spec"
    assert blocker_class(
        "stale_threshold_missing"
    ) == "external_runtime_configuration"
    assert blocker_class(
        "held_out_baseline_lacks_research_provenance"
    ) == "empirical_evidence"
    assert blocker_class(
        "canonical_policy_snapshot_missing"
    ) == "environment_initialization"
    assert blocker_class(
        "canonical_policy_snapshot_invalid"
    ) == "environment_initialization"
    assert blocker_class("live_not_blocked") == "safety_invariant"
    assert blocker_class("unknown_future_blocker") == "internal_contract"
