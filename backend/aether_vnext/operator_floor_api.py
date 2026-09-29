"""GET-only HTTP boundary for the Phase-15 Unified Firm Floor.

The router is intentionally not mounted into the legacy application here. Phase 15
defines and tests the new operator contract; the later Shadow Cutover phase owns
binding it beside the existing runtime. This keeps Phase 15 from creating a second
runtime or silently cutting traffic over early.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import inspect

from fastapi import APIRouter

from aether_vnext.operator_floor import (
    UnifiedFirmFloorSnapshot,
    build_unified_firm_floor,
)


FloorSnapshotProvider = Callable[[], UnifiedFirmFloorSnapshot | Awaitable[UnifiedFirmFloorSnapshot]]


def create_operator_floor_router(
    snapshot_provider: FloorSnapshotProvider,
    *,
    runtime_started_at_utc: datetime | None = None,
) -> APIRouter:
    if not callable(snapshot_provider):
        raise ValueError("snapshot_provider must be callable")

    started_at = runtime_started_at_utc or datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        raise ValueError("runtime_started_at_utc must be timezone-aware")
    started_at = started_at.astimezone(timezone.utc)

    router = APIRouter()

    @router.get("/api/v1/vnext/floor")
    async def read_unified_firm_floor() -> dict[str, object]:
        result = snapshot_provider()
        snapshot = await result if inspect.isawaitable(result) else result
        if not isinstance(snapshot, UnifiedFirmFloorSnapshot):
            raise TypeError(
                "snapshot_provider must return UnifiedFirmFloorSnapshot"
            )
        payload = build_unified_firm_floor(snapshot)
        payload["runtime_started_at_utc"] = started_at.isoformat()
        return payload

    return router
