from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_frontend_is_professional_multi_page_operations_terminal() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    for required in (
        "Command Center",
        "Markets",
        "Pipeline",
        "Trading Floor",
        "Positions",
        "Blotter",
        "Maintenance",
        "Settings",
        "PAPER ACTIVE",
        "LIVE BLOCKED",
        "/api/v1/vnext/floor",
        "/api/v1/vnext/maintenance",
    ):
        assert required in page


def test_frontend_has_no_btc_eth_privileged_presentation() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    forbidden = (
        'assetId="btc"',
        'assetId="eth"',
        "Top 12 Attention",
        "Prototype Stations",
        "BTC and ETH are",
        "Seed + dynamic roaming",
        "heartbeatQuote assetId",
    )
    for value in forbidden:
        assert value not in page


def test_frontend_mutation_transport_is_limited_to_operator_maintenance_controls() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
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
    assert 'method: "POST"' in page
    assert "X-Operator-Token" in page
    assert "onToggle" in page
    assert "onRepair" in page
    assert "RUN SAFE REPAIR NOW" in page


def test_frontend_surfaces_runtime_identity_and_refresh_times() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "App restarted" in page
    assert "runtime_started_at_utc" in page
    assert "Data refreshed" in page
    assert "as_of_utc" in page
    assert "source_revision" in page
    assert 'timeZoneName: "short"' in page


def test_frontend_is_responsive() -> None:
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    assert "@media(max-width:1200px)" in css
    assert "@media(max-width:900px)" in css
    assert "@media(max-width:560px)" in css
    assert ".sidebar" in css
    assert ".workspace" in css
    assert ".marketTable" in css


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


def test_maintenance_repair_control_has_commercial_grade_operation_feedback() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    assert "LAST REPAIR RUN" in page
    assert "REPAIRING…" in page
    assert "last_manual_repair" in page
    assert "Maintenance repair in progress" in page
    assert ".repairSpinner" in css
    assert "@keyframes repairSpin" in css
    assert ".repairProgress" in css


def test_pipeline_flow_map_is_vertical_code_bound_and_explains_real_gates() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    assert "Institutional pipeline flow map" in page
    assert "PLAIN ENGLISH" in page
    assert "DEV CODE NOTE" in page
    assert "PASS ↓" in page
    assert "WAIT ↺" in page
    assert "REJECT → EVIDENCE" in page
    for code_ref in (
        "focus_handoff_rows()",
        "_ordered_dynamic_strategy_work",
        "ingest_market_quotes()",
        "assemble_prototype_crypto_warmup()",
        "evaluate_sniper_fire()",
        "size_runtime_fire_ticket()",
        "evaluate_clerk_ready()",
        "reserve_runtime_ready_ticket()",
        "submit_runtime_reserved_open()",
        "fill_runtime_submitted_open()",
    ):
        assert code_ref in page
    assert ".verticalFlow" in css
    assert ".flowStageV" in css
    assert ".flowGateCard" in css
    assert "grid-template-columns:repeat(9" not in css


def test_pipeline_flow_map_has_reconciliation_predicates_reasons_and_full_exit_path() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    for required in (
        "TRUE CODE PREDICATE",
        "LIVE REASON DISTRIBUTION",
        "UNEXPLAINED",
        "RECONCILED",
        "NOT OBSERVED",
        "Flatten Requested",
        "Close Reserved",
        "Close Submitted",
        "finalize_filled_flat()",
        "Runtime facts this map will not hide",
        "btc_kraken_daily still exists in warm-up",
        "Worker capacity controls simultaneous history I/O only",
        "market_not_ready",
        "history_not_ready",
        "evaluation_error",
    ):
        assert required in page
    assert ".gateTelemetry" in css
    assert ".predicateNote" in css
    assert ".gateReasons" in css
    assert ".constraintGrid" in css


def test_frontend_uses_amber_gold_brand_accent_without_legacy_blue() -> None:
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    assert "--accent:#e7a93b" in css
    assert "--accent-soft:#f2c14e" in css
    assert "--accent-deep:#b8741a" in css
    assert "#5aa9ff" not in css
    assert "#8fbce7" not in css
    assert "#a9d2f7" not in css
    assert "#a9c9e8" not in css


def test_maintenance_ui_exposes_health_mode_and_bounded_repair_timeout() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    app = (_repo_root() / "backend" / "app" / "vnext_maintenance.py").read_text(encoding="utf-8")
    assert "Healthy baseline" in page
    assert "Idle guard" in page
    assert "Repair deadline" in page
    assert "Operation ended after" in page
    assert "AbortController" in page
    assert "TIMED_OUT_IDLE" in app
    assert "TIMED_OUT_TOTAL" in app
    assert "status_code=504" in app



def test_pipeline_surfaces_live_agent_progress_and_uses_progress_heartbeat() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    for required in (
        "LIVE AGENT WORK",
        "Current cycle progress",
        "last_progress_at_utc",
        "completed_dynamic_chunk_count",
        "history_fetch_completed",
        "active_providers",
        "State is derived from observed supervisor movement",
    ):
        assert required in page


def test_frontend_recovery_state_matches_backend_health_semantics() -> None:
    root = _repo_root()
    page = (root / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (root / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    busy_index = page.index('return "BUSY";', page.index("function supervisorState"))
    fault_index = page.index('if (supervisor.last_error) return "FAULT";', page.index("function supervisorState"))
    assert fault_index > busy_index
    assert "REFERENCE CATALOG ONLINE" in page
    assert "CATALOG PRIORITY" in page
    assert "grid-template-columns:repeat(8,minmax(0,1fr))" in css


def test_frontend_distinguishes_catalog_from_runtime_universes() -> None:
    root = _repo_root()
    page = (root / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (root / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    for required in (
        "UNIVERSE CONTRACT",
        "Catalog → commissioned → active work",
        "Kraken commissioned",
        "Current roaming workset",
        "Floor runtime registry",
        "Catalog-visible ≠ commissioned ≠ market-ready ≠ setup-qualified.",
        "NATIVE CATALOG ONLINE",
        "REFERENCE CATALOG ONLINE",
    ):
        assert required in page
    assert "MARKET DATA ONLINE" not in page
    assert ".universeContract" in css
