"""MF-12 read-only operator projection for the dual-domain AETHER Market Fabric.

The projection exposes executable truth and Market Intelligence side by side. It does
not create orders, mutate route authority, or synthesize unavailable values.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.market_fabric_microstructure import MicrostructureSnapshot
from aether_vnext.market_fabric_tape import (
    ExecutableTapeSnapshot,
    MarketIntelligenceSnapshot,
)


def build_market_fabric_operator_row(
    *,
    executable: ExecutableTapeSnapshot,
    intelligence: MarketIntelligenceSnapshot,
    microstructure: MicrostructureSnapshot | None = None,
) -> dict[str, object]:
    if intelligence.instrument_id != executable.instrument_id:
        raise ValueError("operator dual-domain instrument mismatch")

    return {
        "instrument_id": executable.instrument_id,
        "executable": {
            "route_id": executable.route_id,
            "authorized_economic_source_id": executable.authorized_economic_source_id,
            "state": executable.state.value,
            "bid": executable.bid,
            "ask": executable.ask,
            "last_if_printed": executable.last_if_printed,
            "last_credible_age_ms": executable.last_credible_age_ms,
        },
        "intelligence": {
            "evidence_state": intelligence.evidence_state.value,
            "quorum_met": intelligence.quorum_met,
            "raw_witness_count": intelligence.raw_witness_count,
            "effective_independent_count": intelligence.effective_independent_count,
            "in_band_count": intelligence.in_band_count,
            "outside_count": intelligence.outside_count,
            "pending_count": intelligence.pending_count,
            "max_gap_bps": intelligence.max_gap_bps,
            "mutual_spread_bps": intelligence.mutual_spread_bps,
            "classifications": [
                {
                    "witness_id": row.witness_id,
                    "independence_group_id": row.independence_group_id,
                    "classification": row.classification.value,
                    "reason": row.reason,
                    "gap_bps": row.gap_bps,
                    "aligned_mid": row.aligned_mid,
                }
                for row in intelligence.classifications
            ],
        },
        "microstructure": (
            None
            if microstructure is None
            else {
                **asdict(microstructure),
                "executable": False,
            }
        ),
    }


def build_market_fabric_operator_snapshot(
    *,
    rows: Mapping[
        str,
        tuple[
            ExecutableTapeSnapshot,
            MarketIntelligenceSnapshot,
            MicrostructureSnapshot | None,
        ],
    ],
) -> dict[str, object]:
    instruments = [
        build_market_fabric_operator_row(
            executable=executable,
            intelligence=intelligence,
            microstructure=microstructure,
        )
        for _, (executable, intelligence, microstructure) in sorted(rows.items())
    ]
    return {
        "paper_only": bool(PAPER_ONLY),
        "live_blocked": bool(LIVE_BLOCKED),
        "authority": {
            "read_only_projection": True,
            "execution_permission": False,
            "can_change_route": False,
            "can_release_halt": False,
        },
        "domains": {
            "executable_tape": "AUTHORIZED_EXECUTION_ROUTE_ONLY",
            "market_intelligence": "NON_EXECUTABLE_EVIDENCE_AND_DERIVED_ANALYTICS",
        },
        "instrument_count": len(instruments),
        "instruments": instruments,
    }
