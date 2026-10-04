from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.main as main


UTC = timezone.utc


@pytest.mark.asyncio
async def test_startup_recovery_starts_missing_required_supervisor(monkeypatch) -> None:
    calls: list[str] = []
    status = {
        "enabled": True,
        "running": False,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 0,
        "interval_seconds": 15,
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
        "ingress",
        (lambda: dict(status), start, stop),
    )
    main._startup_recovery_last_at.clear()

    result = await main.vnext_startup_recovery("ingress")

    assert result["action"] == "START"
    assert calls == ["start"]
    assert result["paper_only"] is True
    assert result["live_blocked"] is True


@pytest.mark.asyncio
async def test_startup_recovery_restarts_server_classified_stall(monkeypatch) -> None:
    calls: list[str] = []
    old = datetime.now(UTC) - timedelta(minutes=5)
    status = {
        "enabled": True,
        "running": True,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 2,
        "interval_seconds": 15,
        "last_cycle_started_at_utc": old.isoformat(),
        "last_cycle_finished_at_utc": old.isoformat(),
        "last_error": None,
    }

    async def stop() -> None:
        calls.append("stop")
        status["running"] = False

    async def start() -> None:
        calls.append("start")
        status["running"] = True
        status["last_cycle_started_at_utc"] = datetime.now(UTC).isoformat()

    monkeypatch.setattr(main, "configured_vnext_runtime_only", lambda: True)
    monkeypatch.setitem(
        main._STARTUP_RECOVERY_COMPONENTS,
        "strategy",
        (lambda: dict(status), start, stop),
    )
    main._startup_recovery_last_at.clear()

    result = await main.vnext_startup_recovery("strategy")

    assert result["action"] == "RESTART"
    assert result["before_state"] == "STALLED"
    assert calls == ["stop", "start"]


@pytest.mark.asyncio
async def test_startup_recovery_never_targets_maintenance() -> None:
    with pytest.raises(Exception) as exc:
        await main.vnext_startup_recovery("maintenance")
    assert getattr(exc.value, "status_code", None) == 404
