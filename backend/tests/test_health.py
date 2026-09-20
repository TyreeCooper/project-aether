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
