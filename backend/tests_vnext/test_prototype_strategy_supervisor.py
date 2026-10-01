from __future__ import annotations

import asyncio

import pytest

from aether_vnext.prototype_strategy_supervisor import (
    PrototypeStrategySupervisor,
    configured_strategy_enabled,
    configured_strategy_interval_seconds,
    validate_configured_strategy_environment,
)


def test_strategy_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_VNEXT_PROTOTYPE_TRADING_ENABLED", raising=False)
    assert configured_strategy_enabled() is False
    validate_configured_strategy_environment()


def test_enabled_strategy_refuses_non_burnin(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_PROTOTYPE_TRADING_ENABLED", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="only run in burnin"):
        validate_configured_strategy_environment()


def test_strategy_interval_has_hard_lower_bound(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_PROTOTYPE_TRADING_INTERVAL_SECONDS", "4")
    with pytest.raises(ValueError, match="must be >= 5"):
        configured_strategy_interval_seconds()


@pytest.mark.asyncio
async def test_strategy_supervisor_repeats_and_stops() -> None:
    calls = 0

    async def cycle() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "paper_only": True,
            "live_blocked": True,
            "phase18_evidence": False,
        }

    supervisor = PrototypeStrategySupervisor(
        cycle_runner=cycle,
        interval_seconds=0.01,
    )
    await supervisor.start()
    for _ in range(50):
        if calls >= 2:
            break
        await asyncio.sleep(0.01)
    status = supervisor.status()
    assert calls >= 2
    assert status.running is True
    assert status.cycle_count >= 2
    assert status.interval_seconds == 0.01
    assert status.last_error is None
    assert status.paper_only is True
    assert status.live_blocked is True
    await supervisor.stop()
    assert supervisor.status().running is False


@pytest.mark.asyncio
async def test_strategy_supervisor_records_fault_and_recovers() -> None:
    calls = 0

    async def cycle() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary source fault")
        return {"ok": True}

    supervisor = PrototypeStrategySupervisor(
        cycle_runner=cycle,
        interval_seconds=0.01,
    )
    await supervisor.start()
    for _ in range(50):
        if calls >= 2:
            break
        await asyncio.sleep(0.01)
    status = supervisor.status()
    assert calls >= 2
    assert status.running is True
    assert status.cycle_count >= 1
    assert status.last_error is None
    assert status.last_result == {"ok": True}
    await supervisor.stop()
