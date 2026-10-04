from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_phase15_projection_contract_remains_available_to_new_frontend() -> None:
    backend = (_backend_root() / "aether_vnext" / "operator_floor.py").read_text(encoding="utf-8")
    frontend = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    for backend_required in ('"full_universe"', '"top12_attention"', '"seat_queues"', '"open_cockpits"', '"inspection_drawer"'):
        assert backend_required in backend
    for frontend_required in ("Command Center", "Markets", "Pipeline", "Trading Floor", "Positions", "Blotter", "Maintenance", "Settings", "full_universe", "seat_queues", "open_cockpits"):
        assert frontend_required in frontend


def test_phase15_frontend_does_not_fabricate_trade_state() -> None:
    frontend = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    for forbidden in ("station:" + "${selectedStation.asset_id}", "createOrder", "placeOrder", "resetGovernor", "mutateRoute"):
        assert forbidden not in frontend
    assert "no placeholder trade state is invented" in frontend


def test_phase15_floor_api_remains_mounted_through_configured_shadow_bridge() -> None:
    api = (_backend_root() / "aether_vnext" / "operator_floor_api.py").read_text(encoding="utf-8")
    main = (_backend_root() / "app" / "main.py").read_text(encoding="utf-8")
    assert '@router.get("/api/v1/vnext/floor")' in api
    assert "mount_configured_vnext_shadow_floor(app)" in main


def test_phase15_floor_preserves_paper_live_block_and_no_second_runtime() -> None:
    backend = (_backend_root() / "aether_vnext" / "operator_floor.py").read_text(encoding="utf-8")
    frontend = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert '"paper_only": True' in backend
    assert '"live_blocked": True' in backend
    assert '"second_runtime": False' in backend
    assert "PAPER ACTIVE" in frontend
    assert "LIVE BLOCKED" in frontend


def test_phase15_repo_ci_builds_frontend() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "frontend-build:" in workflow
    assert "npm run build" in workflow
