"""App lifecycle bridge for the autonomous vNext PAPER strategy supervisor."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from aether_vnext.prototype_strategy_supervisor import (
    PrototypeStrategySupervisor,
    configured_strategy_enabled,
    configured_strategy_interval_seconds,
    run_configured_prototype_strategy_cycle,
    status_payload,
    validate_configured_strategy_environment,
)


_supervisor: PrototypeStrategySupervisor | None = None


async def start_configured_vnext_strategy() -> None:
    global _supervisor
    if not configured_strategy_enabled():
        return
    validate_configured_strategy_environment()
    if _supervisor is None:
        _supervisor = PrototypeStrategySupervisor(
            cycle_runner=run_configured_prototype_strategy_cycle,
            interval_seconds=configured_strategy_interval_seconds(),
        )
    await _supervisor.start()


async def stop_configured_vnext_strategy() -> None:
    global _supervisor
    if _supervisor is None:
        return
    await _supervisor.stop()


def configured_vnext_strategy_status() -> dict[str, object]:
    enabled = configured_strategy_enabled()
    if _supervisor is None:
        return {
            "enabled": enabled,
            "running": False,
            "paper_only": True,
            "live_blocked": True,
            "cycle_count": 0,
            "interval_seconds": configured_strategy_interval_seconds(),
            "last_cycle_started_at_utc": None,
            "last_cycle_finished_at_utc": None,
            "last_error": None,
            "last_result": None,
        }
    return status_payload(_supervisor.status(enabled=enabled))


def mount_vnext_strategy_status(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/api/v1/vnext/strategy-runtime")
    async def read_vnext_strategy_runtime() -> dict[str, object]:
        return configured_vnext_strategy_status()

    app.include_router(router)
