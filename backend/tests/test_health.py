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
