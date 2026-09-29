"""GET-only HTTP boundary for the Phase-15 Unified Firm Floor.

The router is intentionally not mounted into the legacy application here. Phase 15
defines and tests the new operator contract; the later Shadow Cutover phase owns
binding it beside the existing runtime. This keeps Phase 15 from creating a second
runtime or silently cutting traffic over early.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import inspect

from fastapi import APIRouter

from aether_vnext.operator_floor import (
    UnifiedFirmFloorSnapshot,
    build_unified_firm_floor,
)


FloorSnapshotProvider = Callable[[], UnifiedFirmFloorSnapshot | Awaitable[UnifiedFirmFloorSnapshot]]


def create_operator_floor_router(
    snapshot_provider: FloorSnapshotProvider,
) -> APIRouter:
    if not callable(snapshot_provider):
        raise ValueError("snapshot_provider must be callable")

    router = APIRouter()

    @router.get("/api/v1/vnext/floor")
    async def read_unified_firm_floor() -> dict[str, object]:
        result = snapshot_provider()
        snapshot = await result if inspect.isawaitable(result) else result
        if not isinstance(snapshot, UnifiedFirmFloorSnapshot):
            raise TypeError(
                "snapshot_provider must return UnifiedFirmFloorSnapshot"
            )
        return build_unified_firm_floor(snapshot)

    return router
