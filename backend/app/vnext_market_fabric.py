"""GET-only API projection for the canonical AETHER five-layer market-truth runtime."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from aether_vnext.market_truth_runtime import configured_market_truth_snapshot


def mount_vnext_market_fabric(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/api/v1/vnext/market-fabric")
    async def read_vnext_market_fabric() -> dict[str, object]:
        payload = configured_market_truth_snapshot()
        if payload.get("paper_only") is not True or payload.get("live_blocked") is not True:
            raise RuntimeError("canonical Market Fabric safety invariant failed")
        if payload.get("architecture") != "AETHER_MARKET_TRUTH_V1":
            raise RuntimeError("canonical Market Fabric architecture identity mismatch")
        return payload

    app.include_router(router)
