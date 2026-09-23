from pathlib import Path

from fastapi.testclient import TestClient

import app.desk as desk_module
from app.main import app


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]


def test_load_002_runtime_contract_reports_active_experiment(monkeypatch):
    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = desk_module.MultiDesk(execution_test_mode=True)
    status = desk.load_002_status_snapshot()

    assert status["load"] == "AETHER-LOAD-002"
    assert status["release"] == "AETHER-LOAD-002-EXP-R1"
    assert status["status"] == "experiment_active"
    assert status["ready"] is False
    assert status["runtime_safe"] is True
    assert status["filters_bypassed"] is True
    assert status["experiment"]["run_id"] == "EXP-R1"
    assert status["experiment"]["target_count"] == 12
    assert status["checks"]
    assert all(status["checks"].values())
    assert status["matrix"]["supported_cells"] == 54
    assert status["matrix"]["unsupported_cells"] == 18
    assert status["matrix"]["live_order_attempted"] is False
    assert len(status["scalp_assets"]) == 7


def test_load_002_status_endpoint_reports_forced_experiment_inactive():
    response = client.get("/api/v1/load-status/aether-load-002")
    assert response.status_code == 200
    body = response.json()
    assert body["release"] == "AETHER-LOAD-002-EXP-R1"
    assert body["status"] != "experiment_active"
    assert body["runtime_safe"] is True
    assert body["filters_bypassed"] is False
    assert body["experiment"]["active"] is False
    assert body["checks"]["live_orders_blocked"] is True


def test_production_workflow_verifies_strategy_test_runtime_contract():
    workflow = (
        ROOT / ".github" / "workflows" / "main_aether-prod-api.yml"
    ).read_text(encoding="utf-8")
    assert "/api/v1/load-status/aether-load-002" in workflow
    assert "AETHER-LOAD-003-B8" in workflow
    assert "Waiting for AETHER-LOAD-003-B8 strategy-test runtime" in workflow
    assert "Expected LOAD-003-B8 strategy-test runtime never became active." in workflow
    assert "/api/v1/desk/execution-matrix" in workflow
    assert 'runtime_mode") == "strategy_test"' in workflow
    assert 'execution_test_mode") is False' in workflow
    assert 'forced_entries_enabled") is False' in workflow
    assert "supported_cells" in workflow
    assert "/api/v1/auth/verify" in workflow
    assert 'auth_code" != "401"' in workflow
    assert 'auth_code" != "503"' in workflow
