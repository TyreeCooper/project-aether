"""Phase-16 shadow mount bridge for the vNext Unified Firm Floor.

This module belongs to the legacy application boundary because Phase 16 mounts the
already-built vNext GET-only Floor beside the existing runtime. It does not start a
vNext trading runtime, does not mutate Firm state, and exposes no mutation transport.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from aether_vnext.operator_floor import UnifiedFirmFloorSnapshot
from aether_vnext.operator_floor_api import create_operator_floor_router


FloorSnapshotProvider = Callable[[], UnifiedFirmFloorSnapshot]


def mount_vnext_shadow_floor(
    app: FastAPI,
    *,
    snapshot_provider: FloorSnapshotProvider,
) -> None:
    """Mount the Phase-15 GET-only router into an existing FastAPI application."""
    if not isinstance(app, FastAPI):
        raise ValueError("app must be a FastAPI instance")
    if not callable(snapshot_provider):
        raise ValueError("snapshot_provider must be callable")

    app.include_router(create_operator_floor_router(snapshot_provider))


def shadow_floor_contract() -> dict[str, object]:
    """Return immutable Phase-16 mount invariants for operator diagnostics."""
    return {
        "phase": 16,
        "mode": "shadow",
        "path": "/api/v1/vnext/floor",
        "read_only": True,
        "second_runtime": False,
        "paper_only": True,
        "live_blocked": True,
        "legacy_fallback_allowed": False,
        "mutation_methods": (),
    }
