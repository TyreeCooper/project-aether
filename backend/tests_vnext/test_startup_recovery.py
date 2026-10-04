from __future__ import annotations

import pytest

import app.main as main


@pytest.mark.asyncio
async def test_startup_recovery_starts_missing_discovery_supervisor(monkeypatch) -> None:
    calls: list[str] = []
    status = {
        "enabled": True,
        "running": False,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 0,
        "interval_seconds": 60,
        "last_cycle_started_at_utc": None,
        "last_cycle_finished_at_utc": None,
        "last_error": None,
    }

    async def start() -> None:
        calls.append("start")
        status["running"] = True

    async def stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(main, "configured_vnext_runtime_only", lambda: True)
    monkeypatch.setitem(
        main._STARTUP_RECOVERY_COMPONENTS,
        "discovery",
        (lambda: dict(status), start, stop),
    )
    main._startup_recovery_last_at.clear()

    result = await main.vnext_startup_recovery("discovery")
    assert result["action"] == "START"
    assert calls == ["start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("component", ["ingress", "tape", "strategy"])
async def test_legacy_market_authority_cannot_be_restarted(component, monkeypatch) -> None:
    monkeypatch.setattr(main, "configured_vnext_runtime_only", lambda: True)
    with pytest.raises(Exception) as exc:
        await main.vnext_startup_recovery(component)
    assert getattr(exc.value, "status_code", None) == 409
    assert "quarantined" in str(getattr(exc.value, "detail", "")).lower()


@pytest.mark.asyncio
async def test_startup_recovery_never_targets_maintenance(monkeypatch) -> None:
    monkeypatch.setattr(main, "configured_vnext_runtime_only", lambda: True)
    with pytest.raises(Exception) as exc:
        await main.vnext_startup_recovery("maintenance")
    assert getattr(exc.value, "status_code", None) == 404
