from pathlib import Path

from fastapi.testclient import TestClient

import app.desk as desk_module
from app.main import app


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]


def test_load_002_runtime_contract_is_ready(monkeypatch):
    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = desk_module.MultiDesk(execution_test_mode=False)
    status = desk.load_002_status_snapshot()

    assert status["load"] == "AETHER-LOAD-002"
    assert status["release"] == "AETHER-LOAD-002-B7"
    assert status["status"] == "ready"
    assert status["ready"] is True
    assert status["checks"]
    assert all(status["checks"].values())
    assert status["matrix"]["supported_cells"] == 54
    assert status["matrix"]["unsupported_cells"] == 18
    assert status["matrix"]["live_order_attempted"] is False
    assert len(status["scalp_assets"]) == 7


def test_load_002_status_endpoint_exposes_runtime_contract():
    response = client.get("/api/v1/load-status/aether-load-002")
    assert response.status_code == 200
    body = response.json()
    assert body["release"] == "AETHER-LOAD-002-B7"
    assert body["ready"] is True
    assert body["checks"]["execution_test_off"] is True
    assert body["checks"]["live_orders_blocked"] is True


def test_production_workflow_verifies_load_002_contract():
    workflow = (
        ROOT / ".github" / "workflows" / "main_aether-prod-api.yml"
    ).read_text(encoding="utf-8")
    assert "/api/v1/load-status/aether-load-002" in workflow
    assert "AETHER-LOAD-002-B7" in workflow
    assert "/api/v1/desk/execution-matrix" in workflow
    assert 'execution_test_mode") is False' in workflow
    assert "supported_cells" in workflow
    assert "/api/v1/auth/verify" in workflow
    assert 'auth_code" != "401"' in workflow
    assert 'auth_code" != "503"' in workflow
