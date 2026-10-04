"""B10 closeout audit for canonical AETHER Market Truth authority."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


LEGACY_MARKET_AUTHORITY_COMPONENTS = ("ingress", "tape", "strategy")


@dataclass(frozen=True, slots=True)
class MarketTruthCloseout:
    deployment_ready: bool
    first_proof_complete: bool
    blockers: tuple[str, ...]
    architecture: str | None
    route_count: int
    legacy_authority_quarantined: bool


def evaluate_market_truth_closeout(
    snapshot: Mapping[str, object],
    *,
    legacy_statuses: Mapping[str, Mapping[str, object]],
) -> MarketTruthCloseout:
    blockers: list[str] = []
    architecture = (
        None if snapshot.get("architecture") is None
        else str(snapshot.get("architecture"))
    )
    if architecture != "AETHER_MARKET_TRUTH_V1":
        blockers.append("canonical_architecture_not_active")
    if snapshot.get("paper_only") is not True:
        blockers.append("paper_only_not_proven")
    if snapshot.get("live_blocked") is not True:
        blockers.append("live_block_not_proven")

    authority = snapshot.get("authority")
    authority = authority if isinstance(authority, Mapping) else {}
    if authority.get("witness_can_replace_executable_price") is not False:
        blockers.append("witness_price_authority_not_blocked")
    if authority.get("automatic_execution_venue_switch_allowed") is not False:
        blockers.append("automatic_route_switch_not_blocked")

    routes = snapshot.get("routes")
    route_rows = routes if isinstance(routes, list) else []
    route_count = len(route_rows)
    first_proof = snapshot.get("first_proof")
    first_proof = first_proof if isinstance(first_proof, Mapping) else {}
    first_proof_complete = first_proof.get("passed") is True
    if not first_proof_complete and route_count > 1:
        blockers.append("first_proof_route_limit_violated")

    runtime = snapshot.get("runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    if runtime.get("running") is not True:
        blockers.append("canonical_runtime_not_running")

    legacy_ok = True
    for name in LEGACY_MARKET_AUTHORITY_COMPONENTS:
        row = legacy_statuses.get(name) or {}
        if row.get("enabled") is not False or row.get("running") is not False:
            legacy_ok = False
            blockers.append(f"legacy_{name}_authority_not_quarantined")

    return MarketTruthCloseout(
        deployment_ready=not blockers,
        first_proof_complete=first_proof_complete,
        blockers=tuple(blockers),
        architecture=architecture,
        route_count=route_count,
        legacy_authority_quarantined=legacy_ok,
    )
