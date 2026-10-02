from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_phase15_frontend_contains_complete_unified_floor_composition() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    for required in (
        "Unified Firm Floor",
        "Full Universe",
        "Top 12 Attention",
        "Seat Queues",
        "Open Position Cockpits",
        "Inspection Drawer",
        "PAPER ONLY",
        "LIVE BLOCKED",
        "/api/v1/vnext/floor",
    ):
        assert required in page


def test_phase15_frontend_mutation_transport_is_limited_to_operator_maintenance_controls() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )

    # The original Floor remains free of trading/risk/governor mutation controls.
    for forbidden in (
        'method: "PUT"',
        'method: "PATCH"',
        'method: "DELETE"',
        "createOrder",
        "placeOrder",
        "resetGovernor",
        "mutateRoute",
    ):
        assert forbidden not in page

    # POST is now intentionally present only for authenticated Maintenance
    # controls/repairs. These endpoints cannot create trades or enable LIVE.
    assert 'method: "POST"' in page
    assert "/api/v1/vnext/maintenance" in page
    assert "X-Operator-Token" in page
    assert "onMaintenanceToggle" in page
    assert "onMaintenanceRepair" in page
    assert "RUN SAFE REPAIR NOW" in page


def test_phase15_floor_is_responsive_for_desktop_and_mobile() -> None:
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(
        encoding="utf-8"
    )
    assert "@media (max-width: 780px)" in css
    assert "@media (max-width: 480px)" in css
    assert ".inspectionDrawer" in css
    assert ".universeGrid" in css
    assert ".attentionGrid" in css


def test_floor_header_surfaces_runtime_restart_and_data_refresh_times() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )

    assert "App restarted" in page
    assert "runtime_started_at_utc" in page
    assert "Data refreshed" in page
    assert "as_of_utc" in page
    assert 'timeZoneName: "short"' in page


def test_floor_surfaces_fresh_test_epoch_bank_and_blotter_confirmation() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(
        encoding="utf-8"
    )

    assert "Paper test status" in page
    assert "Test run" in page
    assert "Starting bank" in page
    assert "Blotter" in page
    assert "paper_test" in page
    assert "seed_bank_usd" in page
    assert "blotter_trade_count" in page
    assert ".testStatus" in css


def test_vnext_frontend_is_static_exported_for_same_origin_azure_mount() -> None:
    root = _repo_root()
    page = (root / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    config = (root / "frontend" / "next.config.js").read_text(encoding="utf-8")
    main = (root / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert 'output: "export"' in config
    assert 'basePath: "/vnext"' in config
    assert 'trailingSlash: true' in config
    assert 'process.env.NEXT_PUBLIC_API_BASE || ""' in page
    assert 'Path(__file__).parent / "vnext_ui"' in main
    assert 'app.mount("/vnext", StaticFiles(directory=VNEXT_UI, html=True)' in main


def test_floor_header_surfaces_deployed_build_revision() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(
        encoding="utf-8"
    )

    assert "<b>Build</b>" in page
    assert "floor?.build?.source_revision" in page
    assert ".slice(0, 8)" in page
    assert "repeat(6, minmax(0, 1fr))" in css
