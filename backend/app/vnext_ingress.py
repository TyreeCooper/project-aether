"""App-service lifecycle bridge for the autonomous vNext Kraken ingress worker."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from aether_vnext.kraken_ingress_supervisor import (
    KrakenIngressSupervisor,
    configured_ingress_enabled,
    configured_ingress_interval_seconds,
    run_configured_kraken_ingress_cycle,
    status_payload,
    validate_configured_ingress_environment,
)


_supervisor: KrakenIngressSupervisor | None = None


async def start_configured_vnext_ingress() -> None:
    global _supervisor
    if not configured_ingress_enabled():
        return
    validate_configured_ingress_environment()
    if _supervisor is None:
        _supervisor = KrakenIngressSupervisor(
            cycle_runner=run_configured_kraken_ingress_cycle,
            interval_seconds=configured_ingress_interval_seconds(),
        )
    await _supervisor.start()


async def stop_configured_vnext_ingress() -> None:
    global _supervisor
    if _supervisor is None:
        return
    await _supervisor.stop()


def configured_vnext_ingress_status() -> dict[str, object]:
    enabled = configured_ingress_enabled()
    if _supervisor is None:
        return {
            "enabled": enabled,
            "running": False,
            "paper_only": True,
            "live_blocked": True,
            "cycle_count": 0,
            "last_cycle_started_at_utc": None,
            "last_cycle_finished_at_utc": None,
            "last_error": None,
            "last_result": None,
        }
    return status_payload(_supervisor.status(enabled=enabled))


def mount_vnext_ingress_status(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/api/v1/vnext/ingress-runtime")
    async def read_vnext_ingress_runtime() -> dict[str, object]:
        return configured_vnext_ingress_status()

    app.include_router(router)
