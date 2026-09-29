from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_phase15_completion_gate_is_present_in_projection_and_frontend() -> None:
    backend = (_backend_root() / "aether_vnext" / "operator_floor.py").read_text(
        encoding="utf-8"
    )
    frontend = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    for backend_required in (
        '"full_universe"',
        '"top12_attention"',
        '"seat_queues"',
        '"open_cockpits"',
        '"inspection_drawer"',
    ):
        assert backend_required in backend
    for frontend_required in (
        "Full Universe",
        "Top 12 Attention",
        "Seat Queues",
        "Open Position Cockpits",
        "Inspection Drawer",
    ):
        assert frontend_required in frontend


def test_phase15_frontend_does_not_fabricate_drawer_lineage() -> None:
    frontend = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    assert "station:${selectedStation.asset_id}" not in frontend
    assert (
        "Canonical lineage drawer details are unavailable for this station "
        "in the current snapshot."
    ) in frontend
    assert "No legacy fallback and no placeholder trading state is substituted." in frontend


def test_phase15_floor_api_remains_unmounted_before_shadow_cutover() -> None:
    api = (_backend_root() / "aether_vnext" / "operator_floor_api.py").read_text(
        encoding="utf-8"
    )
    legacy_main = (_backend_root() / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    assert '@router.get("/api/v1/vnext/floor")' in api
    assert "operator_floor_api" not in legacy_main
    assert "create_operator_floor_router" not in legacy_main


def test_phase15_floor_preserves_paper_live_block_and_no_second_runtime() -> None:
    backend = (_backend_root() / "aether_vnext" / "operator_floor.py").read_text(
        encoding="utf-8"
    )
    frontend = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    assert '"paper_only": True' in backend
    assert '"live_blocked": True' in backend
    assert '"second_runtime": False' in backend
    assert "PAPER ONLY" in frontend
    assert "LIVE BLOCKED" in frontend


def test_phase15_repo_ci_builds_frontend() -> None:
    workflow = (
        _repo_root() / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    assert "frontend-build:" in workflow
    assert "Build Unified Firm Floor" in workflow
    assert "npm run build" in workflow
