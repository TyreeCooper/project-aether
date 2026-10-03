"""FastAPI bridge for the vNext provider discovery supervisor."""
from __future__ import annotations

from fastapi import FastAPI

from aether_vnext.provider_discovery_supervisor import (
    ProviderDiscoverySupervisor,
    configured_discovery_enabled,
    configured_discovery_interval_seconds,
    configured_discovery_initial_delay_seconds,
    run_configured_provider_discovery_cycle,
    status_payload,
    validate_configured_discovery_environment,
)


_supervisor: ProviderDiscoverySupervisor | None = None


def _instance() -> ProviderDiscoverySupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = ProviderDiscoverySupervisor(
            cycle_runner=run_configured_provider_discovery_cycle,
            interval_seconds=configured_discovery_interval_seconds(),
            initial_delay_seconds=configured_discovery_initial_delay_seconds(),
        )
    return _supervisor


async def start_configured_vnext_discovery() -> None:
    validate_configured_discovery_environment()
    if configured_discovery_enabled():
        await _instance().start()


async def stop_configured_vnext_discovery() -> None:
    if _supervisor is not None:
        await _supervisor.stop()


def current_discovery_status() -> dict[str, object]:
    if _supervisor is None:
        return {
            "enabled": configured_discovery_enabled(),
            "running": False,
            "paper_only": True,
            "live_blocked": True,
            "cycle_count": 0,
            "interval_seconds": configured_discovery_interval_seconds(),
            "initial_delay_seconds": configured_discovery_initial_delay_seconds(),
            "last_cycle_started_at_utc": None,
            "last_cycle_finished_at_utc": None,
            "last_error": None,
            "last_result": None,
        }
    return status_payload(_supervisor.status(enabled=configured_discovery_enabled()))


def mount_vnext_discovery_status(app: FastAPI) -> None:
    @app.get("/api/v1/vnext/discovery-runtime")
    async def discovery_runtime() -> dict[str, object]:
        return current_discovery_status()
