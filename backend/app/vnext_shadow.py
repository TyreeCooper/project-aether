"""Phase-16 shadow mount bridge for the vNext Unified Firm Floor.

The shadow route reads only from the dedicated vNext burn-in PostgreSQL target.
If that target is not explicitly configured or cannot be read, the route fails
closed with HTTP 503. It never substitutes legacy desk state and never starts a
second trading runtime.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.operator_floor import UnifiedFirmFloorSnapshot
from aether_vnext.operator_floor_api import create_operator_floor_router
from aether_vnext.shadow_floor_snapshot import build_shadow_floor_snapshot
from aether_vnext.store import VNextStore


FloorSnapshotProvider = Callable[
    [],
    UnifiedFirmFloorSnapshot | Awaitable[UnifiedFirmFloorSnapshot],
]


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


async def load_configured_vnext_shadow_snapshot() -> UnifiedFirmFloorSnapshot:
    """Read one Floor snapshot from the dedicated isolated vNext burn-in book."""
    try:
        config = VNextDatabaseConfig.from_environment()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "vNext shadow Floor unavailable: dedicated burn-in database "
                "configuration is not valid"
            ),
        ) from exc

    try:
        async with open_vnext_engine(config) as engine:
            async with engine.connect() as conn:
                as_of_utc = datetime.now(timezone.utc)

                def _read(sync_conn):
                    return build_shadow_floor_snapshot(
                        sync_conn,
                        store=VNextStore(),
                        as_of_utc=as_of_utc,
                    )

                return await conn.run_sync(_read)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "vNext shadow Floor unavailable: dedicated burn-in book "
                "could not be read"
            ),
        ) from exc


def mount_configured_vnext_shadow_floor(app: FastAPI) -> None:
    """Mount the canonical shadow reader without opening a database at startup."""
    mount_vnext_shadow_floor(
        app,
        snapshot_provider=load_configured_vnext_shadow_snapshot,
    )


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
        "database_source": "dedicated_aether_vnext_burnin",
        "mutation_methods": (),
    }
