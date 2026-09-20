from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["env"] == "paper"


def test_bot_starts_offline():
    response = client.get("/api/v1/bot")
    assert response.json()["state"] == "OFFLINE"


def test_status_route_exposes_safety_flags():
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["paper_mode"] is True
    assert body["live_blocked"] is True
    assert "flatten_lock" in body


def test_performance_route_exposes_cost_and_risk_metrics():
    response = client.get("/api/v1/performance")
    assert response.status_code == 200
    body = response.json()
    assert "net_realized_pnl" in body
    assert "total_fees" in body
    assert "total_spread_cost" in body
    assert "total_slippage_cost" in body
    assert "max_drawdown_pct" in body


def test_orders_trades_and_positions_routes_exist():
    assert client.get("/api/v1/orders").status_code == 200
    assert client.get("/api/v1/trades").status_code == 200
    positions = client.get("/api/v1/positions")
    assert positions.status_code == 200
    assert "positions" in positions.json()
