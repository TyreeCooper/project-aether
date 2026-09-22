from fastapi.testclient import TestClient

from app.main import app
from app.universe import ASSETS


READ_ENDPOINTS = [
    "/",
    "/api/v1/health",
    "/api/v1/floor",
    "/api/v1/settings",
    "/api/v1/desk/live-trades",
    "/api/v1/desk/events",
    "/api/v1/desk/blotter",
    "/api/v1/desk/fills",
    "/api/v1/live",
    "/api/v1/storage",
    "/api/v1/auth/status",
]


def test_primary_app_surfaces_boot_and_return_success():
    with TestClient(app) as client:
        for path in READ_ENDPOINTS:
            response = client.get(path)
            assert response.status_code == 200, (
                path,
                response.status_code,
                response.text[:500],
            )


def test_all_official_asset_pages_return_success():
    with TestClient(app) as client:
        for asset in ASSETS:
            response = client.get(f"/api/v1/assets/{asset['id']}")
            assert response.status_code == 200, (
                asset["id"],
                response.status_code,
                response.text[:500],
            )


def test_root_references_static_assets_that_exist():
    with TestClient(app) as client:
        html = client.get("/").text
        for path in (
            "/static/aether-app.js",
            "/static/aether-chart.js",
            "/static/aether-app.css",
            "/static/aether-fit.css",
            "/static/aether-mark.svg",
        ):
            assert path in html
            response = client.get(path)
            assert response.status_code == 200, path


def test_live_and_floor_contracts_match_frontend_expectations():
    with TestClient(app) as client:
        floor = client.get("/api/v1/floor").json()
        live = client.get("/api/v1/desk/live-trades").json()

    assert isinstance(floor.get("assets"), list)
    assert len(floor["assets"]) >= 12
    assert isinstance(floor.get("portfolio"), dict)
    assert isinstance(floor.get("engine"), dict)
    assert isinstance(live.get("items"), list)
    assert isinstance(live.get("watch"), list)
    assert isinstance(live.get("events"), list)
    assert isinstance(live.get("open_count"), int)
