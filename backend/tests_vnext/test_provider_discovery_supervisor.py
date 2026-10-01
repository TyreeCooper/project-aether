import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_vnext.provider_discovery import DiscoveryInstrument
from aether_vnext.provider_discovery_supervisor import (
    ProviderDiscoverySupervisor,
    build_provider_focus_snapshot,
    current_provider_focus_snapshot,
    discovery_progress_payload,
    run_configured_provider_discovery_cycle,
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


def test_focus_snapshot_has_top100_per_online_provider_and_explicit_missing_provider() -> None:
    universes = {
        "Kraken": tuple(_row("Kraken", f"K{i}", i, 1000 * i) for i in range(1, 131)),
        "IBKR": tuple(_row("IBKR", f"S{i}", i / 10, 100000 * i) for i in range(1, 131)),
        "tastyfx": tuple(_row("tastyfx", f"FX{i}", i / 100, 0) for i in range(1, 131)),
        "NinjaTrader": (),
    }
    snapshot = build_provider_focus_snapshot(
        universes,
        provider_errors={},
        as_of_utc=NOW,
    )
    assert snapshot["focus_count"] == 300
    assert snapshot["scout_received_count"] == 300
    assert snapshot["runtime_evaluable_count"] >= 0
    assert snapshot["runtime_requirements_count"] >= 0
    assert snapshot["scout_queued_count"] == 0
    assert snapshot["discovery_only_count"] == 0
    assert len(snapshot["scout_handoff"]) == 300
    assert all(row["state"] == "SCOUT_RECEIVED" for row in snapshot["scout_handoff"])
    assert len(snapshot["providers"]["Kraken"]["top100"]) == 100
    assert len(snapshot["providers"]["IBKR"]["top100"]) == 100
    assert len(snapshot["providers"]["tastyfx"]["top100"]) == 100
    assert snapshot["providers"]["NinjaTrader"]["status"] == "online"
    assert snapshot["providers"]["NinjaTrader"]["focus_count"] == 0
    assert snapshot["online_provider_count"] == 4
    assert snapshot["on_hold_provider_count"] == 0
    assert snapshot["focus_limit_per_provider"] == 100
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



def test_provider_cycle_times_out_one_source_and_completes(monkeypatch) -> None:
    async def fast_kraken():
        return (_row("Kraken", "BTC/USD", 1.0, 1000.0),)

    async def slow_tastyfx():
        await asyncio.sleep(0.05)
        return (_row("tastyfx", "EUR/USD", 0.1, 100.0),)

    async def fast_ninja():
        raise RuntimeError("ninja_reference_unavailable")

    async def fast_ibkr():
        return (_row("IBKR", "AAPL", 0.3, 10000.0),)

    monkeypatch.setattr(
        "aether_vnext.provider_discovery_supervisor.fetch_kraken_discovery_universe",
        fast_kraken,
    )
    monkeypatch.setattr(
        "aether_vnext.provider_discovery_supervisor.fetch_tastyfx_public_universe",
        slow_tastyfx,
    )
    monkeypatch.setattr(
        "aether_vnext.provider_discovery_supervisor.fetch_ninjatrader_public_universe",
        fast_ninja,
    )
    monkeypatch.setattr(
        "aether_vnext.provider_discovery_supervisor.fetch_ibkr_us_equity_public_universe",
        fast_ibkr,
    )
    monkeypatch.setattr(
        "aether_vnext.provider_discovery_supervisor.configured_provider_fetch_timeout_seconds",
        lambda: 0.01,
    )

    snapshot = asyncio.run(run_configured_provider_discovery_cycle())
    assert snapshot["providers"]["Kraken"]["status"] == "online"
    assert snapshot["providers"]["tastyfx"]["status"] == "unavailable"
    assert "provider_fetch_timeout" in snapshot["providers"]["tastyfx"]["reason"]
    assert snapshot["providers"]["NinjaTrader"]["status"] == "unavailable"
    assert "ninja_reference_unavailable" in snapshot["providers"]["NinjaTrader"]["reason"]
    assert snapshot["providers"]["IBKR"]["status"] == "online"

    current = current_provider_focus_snapshot()
    assert current is not None
    assert current["providers"]["Kraken"]["status"] == "online"
    current["providers"]["Kraken"]["status"] = "mutated-test-copy"
    assert current_provider_focus_snapshot()["providers"]["Kraken"]["status"] == "online"

    progress = discovery_progress_payload()
    assert progress["cycle_state"] == "complete"
    assert progress["current_provider"] is None
    assert progress["providers"]["tastyfx"]["state"] == "timeout"
    assert progress["providers"]["IBKR"]["state"] == "online"
    assert progress["providers"]["NinjaTrader"]["state"] == "error"
