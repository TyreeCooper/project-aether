"""Read-only runtime projection for AETHER Market Fabric v3.

This compatibility surface composes the currently commissioned executable ingress
with legacy Tape evidence without allowing consensus prices to replace executable
route prices. Unknown v3-only runtime facts remain null until their persistence paths
are commissioned.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from fastapi import APIRouter, FastAPI

from app.vnext_ingress import configured_vnext_ingress_status
from app.vnext_tape import load_configured_vnext_tape_snapshot
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.market_fabric_runtime_identity import (
    declared_effective_independence_groups,
    runtime_source_identity,
)


UTC = timezone.utc


def build_market_fabric_runtime_snapshot(
    *,
    ingress_status: Mapping[str, object],
    tape_snapshot: Mapping[str, object],
    as_of_utc: datetime,
) -> dict[str, object]:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    ingress_result = ingress_status.get("last_result")
    ingress_result = ingress_result if isinstance(ingress_result, Mapping) else {}
    raw_quotes = ingress_result.get("quotes")
    quotes = raw_quotes if isinstance(raw_quotes, list) else []

    evidence_assets = tape_snapshot.get("assets")
    evidence_assets = evidence_assets if isinstance(evidence_assets, list) else []

    executable_by_asset: dict[str, Mapping[str, object]] = {}
    for raw in quotes:
        if not isinstance(raw, Mapping):
            continue
        asset_id = str(raw.get("asset_id") or "").strip().lower()
        if not asset_id:
            continue
        prior = executable_by_asset.get(asset_id)
        current_key = str(raw.get("reference_ts_utc") or raw.get("received_ts_utc") or "")
        prior_key = (
            ""
            if prior is None
            else str(prior.get("reference_ts_utc") or prior.get("received_ts_utc") or "")
        )
        if prior is None or current_key >= prior_key:
            executable_by_asset[asset_id] = raw

    evidence_by_asset: dict[str, Mapping[str, object]] = {}
    for raw in evidence_assets:
        if not isinstance(raw, Mapping):
            continue
        asset_id = str(raw.get("asset_id") or "").strip().lower()
        if asset_id:
            evidence_by_asset[asset_id] = raw

    instrument_ids = sorted(set(executable_by_asset) | set(evidence_by_asset))
    instruments: list[dict[str, object]] = []
    for asset_id in instrument_ids:
        executable = executable_by_asset.get(asset_id)
        evidence = evidence_by_asset.get(asset_id)

        bid = None if executable is None else executable.get("bid")
        ask = None if executable is None else executable.get("ask")
        executable_state = (
            "EXECUTABLE"
            if executable is not None and bid is not None and ask is not None
            else "NOT_OBSERVED"
        )
        evidence_state = (
            "NOT_OBSERVED"
            if evidence is None
            else str(evidence.get("state") or "NOT_OBSERVED")
        )

        accepted_source_ids = (
            ()
            if evidence is None
            else tuple(
                str(value)
                for value in (evidence.get("accepted_source_ids") or ())
            )
        )
        declared_groups = declared_effective_independence_groups(
            accepted_source_ids
        )
        source_identities = tuple(
            identity
            for source_id in accepted_source_ids
            for identity in (runtime_source_identity(source_id),)
            if identity is not None
        )

        instruments.append(
            {
                "asset_id": asset_id,
                "executable": {
                    "state": executable_state,
                    "source_id": (
                        None if executable is None else executable.get("source_id")
                    ),
                    "venue": None if executable is None else executable.get("venue"),
                    "bid": bid,
                    "ask": ask,
                    "last": None if executable is None else executable.get("last"),
                    "mark": None if executable is None else executable.get("mark"),
                    "reference_ts_utc": (
                        None
                        if executable is None
                        else executable.get("reference_ts_utc")
                    ),
                },
                "intelligence": {
                    "evidence_state": evidence_state,
                    "evidence_composite_id": (
                        None if evidence is None else evidence.get("composite_id")
                    ),
                    "raw_witness_count": (
                        None if evidence is None else evidence.get("source_count")
                    ),
                    "declared_independence_group_count": len(declared_groups),
                    "declared_independence_group_ids": list(declared_groups),
                    # Empirical collapse requires persisted residual history and is
                    # intentionally not inferred from a single runtime snapshot.
                    "empirical_independence_group_count": None,
                    "source_identities": list(source_identities),
                    "quorum_required": (
                        None if evidence is None else evidence.get("quorum_required")
                    ),
                    "agreement_bps": (
                        None if evidence is None else evidence.get("agreement_bps")
                    ),
                    "provenance_complete": (
                        None if evidence is None else evidence.get("provenance_complete")
                    ),
                    "derived_reference_mark": (
                        None if evidence is None else evidence.get("composite_mark")
                    ),
                    "derived_reference_executable": False,
                },
            }
        )

    return {
        "as_of_utc": as_of_utc.astimezone(UTC).isoformat(),
        "paper_only": bool(PAPER_ONLY),
        "live_blocked": bool(LIVE_BLOCKED),
        "authority": {
            "read_only_projection": True,
            "execution_permission": False,
            "consensus_can_replace_executable_price": False,
        },
        "runtime_contract": {
            "executable_domain": "commissioned_ingress_route",
            "intelligence_domain": "legacy_tape_evidence_compatibility",
            "declared_independence_runtime": "BOUND",
            "empirical_independence_runtime": "NOT_OBSERVED",
        },
        "instrument_count": len(instruments),
        "instruments": instruments,
        "ingress_runtime": {
            "enabled": ingress_status.get("enabled"),
            "running": ingress_status.get("running"),
            "cycle_count": ingress_status.get("cycle_count"),
            "last_error": ingress_status.get("last_error"),
        },
        "evidence_runtime": tape_snapshot.get("runtime"),
    }


async def load_configured_market_fabric_runtime_snapshot() -> dict[str, object]:
    tape = await load_configured_vnext_tape_snapshot()
    payload = build_market_fabric_runtime_snapshot(
        ingress_status=configured_vnext_ingress_status(),
        tape_snapshot=tape,
        as_of_utc=datetime.now(UTC),
    )
    if payload.get("paper_only") is not True or payload.get("live_blocked") is not True:
        raise RuntimeError("AETHER Market Fabric safety invariant failed")
    return payload


def mount_vnext_market_fabric(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/api/v1/vnext/market-fabric")
    async def read_vnext_market_fabric() -> dict[str, object]:
        return await load_configured_market_fabric_runtime_snapshot()

    app.include_router(router)
