from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

AUTH = {"Authorization": "Bearer dev-only-change-me"}
STEP_UP = {
    "Authorization": "Bearer dev-only-change-me",
    "X-Aether-Step-Up": "dev-only-step-up-change-me",
}


def test_health_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["env"] == "paper"


def test_operator_routes_require_auth():
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/account").status_code == 401


def test_step_up_routes_require_second_secret():
    assert client.post("/api/v1/bot/start", headers=AUTH).status_code == 403
    assert client.post("/api/v1/risk/unlock", headers=AUTH).status_code == 403


def test_bot_starts_offline():
    response = client.get("/api/v1/bot", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["state"] == "OFFLINE"


def test_status_route_exposes_safety_flags():
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["paper_mode"] is True
    assert body["live_blocked"] is True
    assert "flatten_lock" in body


def test_performance_route_exposes_cost_and_risk_metrics():
    response = client.get("/api/v1/performance", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert "net_realized_pnl" in body
    assert "total_fees" in body
    assert "total_spread_cost" in body
    assert "total_slippage_cost" in body
    assert "max_drawdown_pct" in body


def test_orders_trades_and_positions_routes_exist():
    assert client.get("/api/v1/orders", headers=AUTH).status_code == 200
    assert client.get("/api/v1/trades", headers=AUTH).status_code == 200
    positions = client.get("/api/v1/positions", headers=AUTH)
    assert positions.status_code == 200
    assert "positions" in positions.json()


def test_stop_and_flatten_need_operator_auth_not_step_up():
    assert client.post("/api/v1/bot/stop", headers=AUTH).status_code == 200
    assert client.post("/api/v1/orders/flatten", headers=AUTH).status_code == 200


def test_step_up_accepts_valid_second_secret():
    response = client.post("/api/v1/risk/unlock", headers=STEP_UP)
    assert response.status_code == 200


def test_kraken_readiness_reports_unconfigured_without_read_only_key():
    response = client.get("/api/v1/venue/kraken/readiness", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["ready"] is False


def test_kraken_reconcile_requires_read_only_credentials():
    response = client.post("/api/v1/venue/kraken/reconcile", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "error": "read_only_credentials_not_configured",
    }


def test_shadow_decisions_route_requires_auth():
    assert client.get("/api/v1/shadow/decisions").status_code == 401


def test_shadow_decisions_route_exposes_mode():
    response = client.get("/api/v1/shadow/decisions", headers=AUTH)
    assert response.status_code == 200
    assert "enabled" in response.json()
    assert "decisions" in response.json()


def test_validate_only_route_requires_step_up():
    response = client.post(
        "/api/v1/venue/kraken/validate-order",
        headers=AUTH,
        json={"side": "buy", "qty": 0.001},
    )
    assert response.status_code == 403


def test_validate_only_route_reports_unconfigured_credentials():
    response = client.post(
        "/api/v1/venue/kraken/validate-order",
        headers=STEP_UP,
        json={"side": "buy", "qty": 0.001},
    )
    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "error": "validate_only_credentials_not_configured",
    }
