import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_vnext.provider_discovery import DiscoveryInstrument
from aether_vnext.provider_discovery_supervisor import (
    ProviderDiscoverySupervisor,
    build_provider_focus_snapshot,
)
from app.vnext_discovery import mount_vnext_discovery_status


NOW = datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)


def _row(provider: str, symbol: str, move: float, volume: float) -> DiscoveryInstrument:
    return DiscoveryInstrument(
        provider=provider,
        symbol=symbol,
        market_data_symbol=symbol,
        execution_symbol=symbol if provider in {"Kraken", "IBKR", "NinjaTrader"} else None,
        asset_class="test",
        price=100.0 + move,
        open_price=100.0,
        high_price=101.0 + move,
        low_price=99.0,
        volume=volume,
        bid=99.99 + move,
        ask=100.01 + move,
        change_pct=move,
        observed_at_utc=NOW,
        source="test",
    )


def test_focus_snapshot_has_top25_per_online_provider_and_explicit_missing_provider() -> None:
    universes = {
        "Kraken": tuple(_row("Kraken", f"K{i}", i, 1000 * i) for i in range(1, 31)),
        "IBKR": tuple(_row("IBKR", f"S{i}", i / 10, 100000 * i) for i in range(1, 31)),
        "tastyfx": tuple(_row("tastyfx", f"FX{i}", i / 100, 0) for i in range(1, 31)),
    }
    snapshot = build_provider_focus_snapshot(
        universes,
        provider_errors={"NinjaTrader": "public_reference_unavailable"},
        as_of_utc=NOW,
    )
    assert snapshot["focus_count"] == 75
    assert snapshot["scout_ready_count"] >= 0
    assert snapshot["scout_ready_count"] + snapshot["discovery_only_count"] == 75
    assert len(snapshot["scout_handoff"]) == 75
    assert len(snapshot["providers"]["Kraken"]["top25"]) == 25
    assert len(snapshot["providers"]["IBKR"]["top25"]) == 25
    assert len(snapshot["providers"]["tastyfx"]["top25"]) == 25
    assert snapshot["providers"]["NinjaTrader"]["status"] == "unavailable"
    assert snapshot["providers"]["Kraken"]["catalog_mode"] == "provider_native"
    assert snapshot["providers"]["IBKR"]["catalog_mode"] == "public_reference_proxy"
    assert snapshot["trading_authority"] is False


def test_discovery_supervisor_cycles_without_execution_authority() -> None:
    calls = 0

    async def cycle():
        nonlocal calls
        calls += 1
        return {
            "paper_only": True,
            "live_blocked": True,
            "trading_authority": False,
            "focus_count": 0,
        }

    async def scenario():
        supervisor = ProviderDiscoverySupervisor(
            cycle_runner=cycle,
            interval_seconds=0.01,
        )
        await supervisor.start()
        await asyncio.sleep(0.035)
        status = supervisor.status()
        await supervisor.stop()
        assert status.running is True
        assert status.cycle_count >= 2
        assert status.paper_only is True
        assert status.live_blocked is True
        assert status.last_result["trading_authority"] is False

    asyncio.run(scenario())
    assert calls >= 2


def test_discovery_supervisor_isolates_blocking_cycle_from_event_loop() -> None:
    async def cycle():
        import time
        time.sleep(0.05)
        return {
            "paper_only": True,
            "live_blocked": True,
            "trading_authority": False,
            "focus_count": 0,
        }

    async def scenario():
        supervisor = ProviderDiscoverySupervisor(
            cycle_runner=cycle,
            interval_seconds=60.0,
        )
        await supervisor.start()
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.005)
        elapsed = asyncio.get_running_loop().time() - started
        # If the blocking cycle ran on the ASGI loop, this sleep would take
        # roughly the full 50ms blocking interval instead of returning promptly.
        assert elapsed < 0.03
        await asyncio.sleep(0.07)
        assert supervisor.status().cycle_count == 1
        await supervisor.stop()

    asyncio.run(scenario())


def test_discovery_supervisor_honors_initial_startup_delay() -> None:
    calls = 0

    async def cycle():
        nonlocal calls
        calls += 1
        return {
            "paper_only": True,
            "live_blocked": True,
            "trading_authority": False,
            "focus_count": 0,
        }

    async def scenario():
        supervisor = ProviderDiscoverySupervisor(
            cycle_runner=cycle,
            interval_seconds=60.0,
            initial_delay_seconds=0.04,
        )
        await supervisor.start()
        await asyncio.sleep(0.01)
        assert calls == 0
        assert supervisor.status().initial_delay_seconds == 0.04
        await asyncio.sleep(0.05)
        assert calls == 1
        await supervisor.stop()

    asyncio.run(scenario())


def test_discovery_status_route_is_get_only(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_PROVIDER_DISCOVERY_ENABLED", "false")
    app = FastAPI()
    mount_vnext_discovery_status(app)
    client = TestClient(app)
    response = client.get("/api/v1/vnext/discovery-runtime")
    assert response.status_code == 200
    assert response.json()["running"] is False
    assert client.post("/api/v1/vnext/discovery-runtime").status_code == 405
