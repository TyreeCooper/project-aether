from fastapi.testclient import TestClient

import app.main as main_module


client = TestClient(main_module.app)


def test_mutations_fail_closed_when_operator_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(main_module, "OPERATOR_TOKEN", "")
    response = client.post("/api/v1/desk/arm")
    assert response.status_code == 503
    assert "read-only" in response.json()["detail"]


def test_operator_verify_requires_exact_server_token(monkeypatch):
    monkeypatch.setattr(main_module, "OPERATOR_TOKEN", "test-secret")

    missing = client.post("/api/v1/auth/verify")
    assert missing.status_code == 401

    wrong = client.post(
        "/api/v1/auth/verify",
        headers={"X-Operator-Token": "wrong"},
    )
    assert wrong.status_code == 401

    correct = client.post(
        "/api/v1/auth/verify",
        headers={"X-Operator-Token": "test-secret"},
    )
    assert correct.status_code == 200
    assert correct.json()["authenticated"] is True


def test_auth_status_reports_verified_session_without_exposing_token(monkeypatch):
    monkeypatch.setattr(main_module, "OPERATOR_TOKEN", "test-secret")

    locked = client.get("/api/v1/auth/status").json()
    assert locked == {
        "configured": True,
        "enforced_on_mutations": True,
        "authenticated": False,
        "read_only": True,
    }

    connected = client.get(
        "/api/v1/auth/status",
        headers={"X-Operator-Token": "test-secret"},
    ).json()
    assert connected["configured"] is True
    assert connected["enforced_on_mutations"] is True
    assert connected["authenticated"] is True
    assert connected["read_only"] is False
    assert "token" not in connected


def test_settings_report_fail_closed_mutation_security(monkeypatch):
    monkeypatch.setattr(main_module, "OPERATOR_TOKEN", "")
    body = client.get("/api/v1/settings").json()
    assert body["security"]["operator_token_configured"] is False
    assert body["security"]["mutations_protected"] is True
    assert body["security"]["read_only_without_verified_token"] is True
