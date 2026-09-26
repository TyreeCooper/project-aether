"""Scout WATCH materialization for AETHER vNext Phase 8.

Scout converts a source-bound Playbook Runtime WATCH candidate into the canonical
durable Setup object. It does not FIRE, size, price execution, admit risk, or move
the Firm book.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from aether_vnext.domain import Lineage, Setup, SetupState
from aether_vnext.playbook_engine import RuntimeWatchCandidate
from aether_vnext.playbooks import (
    asset_risk_hitches,
    cluster_for_asset,
    playbook,
)


def canonical_route_id(*, asset_id: str, horizon: str, side: str) -> str:
    if not asset_id or not horizon or not side:
        raise ValueError("asset_id, horizon, and side are required")
    return f"{asset_id}:{horizon}:{side}"


def build_watch_setup(
    candidate: RuntimeWatchCandidate,
    *,
    setup_id: str,
    firm_event_id: str,
    policy_version: str,
    configuration_hash: str,
    market_observation_id: str,
    trigger_bar_close_exchange_ts: datetime,
    created_at_utc: datetime,
    invalidation: float | None,
    quality: float | None,
    intel_pack: Mapping[str, Any] | None = None,
) -> Setup:
    """Stamp one immutable Scout WATCH claim from a runtime candidate."""
    if not setup_id or not firm_event_id:
        raise ValueError("setup_id and firm_event_id are required")
    if not policy_version or not configuration_hash:
        raise ValueError("policy identity is required")
    if not market_observation_id:
        raise ValueError("market_observation_id is required")
    if trigger_bar_close_exchange_ts.tzinfo is None:
        raise ValueError("trigger_bar_close_exchange_ts must be timezone-aware")
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")

    spec = playbook(candidate.playbook_id)
    if not spec.scout_definition_enabled:
        raise ValueError(
            f"playbook is not operationally Scout-enabled: {candidate.playbook_id}"
        )
    if candidate.asset_id not in spec.allowed_assets:
        raise ValueError("candidate asset violates playbook contract")
    if candidate.side not in spec.allowed_sides:
        raise ValueError("candidate side violates playbook contract")
    if candidate.horizon != spec.horizon:
        raise ValueError("candidate horizon violates playbook contract")

    cluster_id = cluster_for_asset(candidate.asset_id)
    if candidate.family is not spec.family:
        raise ValueError("candidate family violates playbook contract")

    hitches = {
        str(asset_id): float(fraction)
        for asset_id, fraction in asset_risk_hitches(
            candidate.playbook_id
        ).items()
    }
    for hitch_asset, fraction in hitches.items():
        if hitch_asset == candidate.asset_id:
            raise ValueError("cross-asset Risk hitch cannot target itself")
        if fraction <= 0.0:
            raise ValueError("asset-risk hitch fraction must be positive")

    route_id = canonical_route_id(
        asset_id=candidate.asset_id,
        horizon=candidate.horizon,
        side=candidate.side,
    )
    lineage = Lineage(
        asset_id=candidate.asset_id,
        route_id=route_id,
        policy_version=policy_version,
        configuration_hash=configuration_hash,
        market_observation_id=market_observation_id,
        created_at_utc=created_at_utc,
        firm_event_id=firm_event_id,
        setup_id=setup_id,
        playbook_id=spec.playbook_id,
        playbook_version=spec.version,
        risk_cluster_id=cluster_id,
        asset_risk_hitches=hitches,
    )
    return Setup(
        setup_id=setup_id,
        lineage=lineage,
        state=SetupState.WATCH,
        side=candidate.side,
        horizon=candidate.horizon,
        invalidation=invalidation,
        quality=quality,
        intel_pack=dict(intel_pack or {}),
        trigger_bar_close_exchange_ts=trigger_bar_close_exchange_ts,
        exit_contract_complete=bool(candidate.exit_contract_complete),
        exit_contract_gap=candidate.exit_contract_gap,
    )
