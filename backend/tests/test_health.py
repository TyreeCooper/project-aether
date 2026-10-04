from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["env"] == "paper"


def test_bot_remains_in_safe_paper_state():
    response = client.get("/api/v1/bot")
    body = response.json()
    # Lifespan smoke tests may have exercised AETHER_AUTO_RUN first.
    # OFFLINE and IDLE are both safe paper states; neither implies live orders.
    assert body["state"] in {"OFFLINE", "IDLE"}
    live = client.get("/api/v1/live").json()
    assert live["orders_enabled"] is False


def test_health_uses_vnext_runtime_truth_in_sandbox(monkeypatch):
    import app.main as main

    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    active = {
        "enabled": True,
        "running": True,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 3,
        "interval_seconds": 300.0,
        "last_cycle_started_at_utc": "2099-01-01T00:00:00+00:00",
        "last_cycle_finished_at_utc": "2099-01-01T00:00:01+00:00",
        "last_error": None,
        "progress": {
            "cycle_state": "complete",
            "last_progress_at_utc": "2099-01-01T00:00:01+00:00",
        },
    }
    monkeypatch.setattr(main, "current_discovery_status", lambda: dict(active))
    monkeypatch.setattr(main, "configured_vnext_maintenance_status", lambda: dict(active))
    monkeypatch.setattr(main, "configured_market_truth_snapshot", lambda: {
        "architecture": "AETHER_MARKET_TRUTH_V1",
        "paper_only": True,
        "live_blocked": True,
        "layers": {"market_fabric": "EXECUTABLE"},
        "first_proof": {"required": True, "passed": False},
        "runtime": {
            "running": True,
            "bootstrap_ready": True,
            "bootstrap_error": None,
            "last_progress_at_utc": "2099-01-01T00:00:01+00:00",
            "executable_packet_count": 5,
            "witness_packet_count": 4,
        },
    })

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "vnext"
    assert body["paper_mode"] is True
    assert body["live_blocked"] is True
    assert body["pipeline_state"] == "ACTIVE"
    assert body["market_truth_architecture"] == "AETHER_MARKET_TRUTH_V1"
    assert body["supervisor_state"]["market_truth"] == "ACTIVE"
    assert body["supervisor_state"]["ingress"] == "QUARANTINED"
    assert body["supervisor_state"]["tape"] == "QUARANTINED"
    assert body["supervisor_state"]["strategy"] == "QUARANTINED"
    assert body["supervisors"]["ingress"]["authority"] == "QUARANTINED"
    assert body["supervisors"]["market_truth"]["executable_packet_count"] == 5
    assert len(response.content) < 50_000
    assert "watch" not in body
    assert "universe" not in body



def test_runtime_state_uses_live_progress_heartbeat_before_declaring_stall():
    from datetime import datetime, timedelta, timezone
    import app.main as main

    now = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    status = {
        "enabled": True,
        "running": True,
        "cycle_count": 8,
        "interval_seconds": 15.0,
        "last_cycle_started_at_utc": (now - timedelta(minutes=5)).isoformat(),
        "last_cycle_finished_at_utc": (now - timedelta(minutes=6)).isoformat(),
        "last_error": None,
        "progress": {
            "cycle_state": "running",
            "last_progress_at_utc": (now - timedelta(seconds=10)).isoformat(),
        },
    }
    assert main._supervisor_operating_state(status, now=now) == "WORKING"

    status["progress"]["last_progress_at_utc"] = (now - timedelta(minutes=3)).isoformat()
    assert main._supervisor_operating_state(status, now=now) == "STALLED"



def test_runtime_state_treats_fresh_recovery_cycle_as_warming_after_prior_fault():
    from datetime import datetime, timedelta, timezone
    import app.main as main

    now = datetime(2026, 10, 3, 2, 25, tzinfo=timezone.utc)
    status = {
        "enabled": True,
        "running": True,
        "cycle_count": 0,
        "interval_seconds": 15.0,
        "last_cycle_started_at_utc": (now - timedelta(seconds=30)).isoformat(),
        "last_cycle_finished_at_utc": (now - timedelta(seconds=45)).isoformat(),
        "last_error": "TimeoutError:",
        "progress": {
            "cycle_state": "running",
            "phase": "history",
            "last_progress_at_utc": (now - timedelta(seconds=5)).isoformat(),
        },
    }

    assert main._supervisor_operating_state(status, now=now) == "WARMING"

    status["progress"] = {
        "cycle_state": "complete",
        "last_progress_at_utc": (now - timedelta(seconds=5)).isoformat(),
    }
    status["last_cycle_started_at_utc"] = (now - timedelta(seconds=45)).isoformat()
    status["last_cycle_finished_at_utc"] = (now - timedelta(seconds=30)).isoformat()
    assert main._supervisor_operating_state(status, now=now) == "FAULT"


def test_runtime_state_running_zero_cycles_is_warming():
    from datetime import datetime, timezone
    import app.main as main

    now = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
    status = {
        "enabled": True,
        "running": True,
        "cycle_count": 0,
        "interval_seconds": 15.0,
        "last_cycle_started_at_utc": None,
        "last_cycle_finished_at_utc": None,
        "last_error": None,
        "progress": {"cycle_state": "idle", "last_progress_at_utc": None},
    }
    assert main._supervisor_operating_state(status, now=now) == "WARMING"


def test_health_reports_warming_not_degraded_during_cold_start(monkeypatch):
    import app.main as main

    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    warming = {
        "enabled": True,
        "running": True,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 0,
        "interval_seconds": 300.0,
        "last_cycle_started_at_utc": None,
        "last_cycle_finished_at_utc": None,
        "last_error": None,
        "progress": {"cycle_state": "idle", "last_progress_at_utc": None},
    }
    monkeypatch.setattr(main, "current_discovery_status", lambda: dict(warming))
    monkeypatch.setattr(main, "configured_vnext_maintenance_status", lambda: {
        **warming, "enabled": False, "running": False
    })
    monkeypatch.setattr(main, "configured_market_truth_snapshot", lambda: {
        "architecture": "AETHER_MARKET_TRUTH_V1",
        "paper_only": True,
        "live_blocked": True,
        "layers": {"market_fabric": "WARMING"},
        "first_proof": {"required": True, "passed": False},
        "runtime": {
            "running": True,
            "bootstrap_ready": False,
            "bootstrap_error": None,
            "last_progress_at_utc": None,
        },
    })

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_state"] == "WARMING"
    assert body["supervisor_state"]["market_truth"] == "WARMING"
    assert body["supervisor_state"]["ingress"] == "QUARANTINED"

