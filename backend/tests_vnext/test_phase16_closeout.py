from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_phase16_shadow_route_is_get_only_and_mounted_in_existing_app() -> None:
    backend = _backend_root()
    api = (backend / "aether_vnext" / "operator_floor_api.py").read_text(
        encoding="utf-8"
    )
    main = (backend / "app" / "main.py").read_text(encoding="utf-8")

    assert '@router.get("/api/v1/vnext/floor")' in api
    for forbidden in (
        '@router.post("/api/v1/vnext/floor")',
        '@router.put("/api/v1/vnext/floor")',
        '@router.patch("/api/v1/vnext/floor")',
        '@router.delete("/api/v1/vnext/floor")',
    ):
        assert forbidden not in api

    assert "mount_configured_vnext_shadow_floor(app)" in main


def test_phase16_bridge_uses_dedicated_vnext_book_and_has_no_legacy_fallback() -> None:
    bridge = (
        _backend_root() / "app" / "vnext_shadow.py"
    ).read_text(encoding="utf-8")

    assert "VNextDatabaseConfig.from_environment()" in bridge
    assert "open_vnext_engine" in bridge
    assert "build_shadow_floor_snapshot" in bridge
    assert "dedicated_aether_vnext_sandbox" in bridge
    assert "desk.floor_snapshot" not in bridge
    assert "engine.start_loop" not in bridge
    assert "legacy_fallback_allowed" in bridge
    assert "status_code=503" in bridge


def test_phase16_snapshot_projection_uses_canonical_vnext_state_only() -> None:
    snapshot = (
        _backend_root() / "aether_vnext" / "shadow_floor_snapshot.py"
    ).read_text(encoding="utf-8")

    assert "SEED_REGISTRY" in snapshot
    assert 't["market_observations"]' in snapshot
    assert 't["decision_lineage"]' in snapshot
    assert 't["setups"]' in snapshot
    assert 't["tickets"]' in snapshot
    assert 't["order_intents"]' in snapshot
    assert 't["active_positions"]' in snapshot
    assert 't["open_trades"]' in snapshot
    assert 't["governor_state"]' in snapshot
    assert "from app" not in snapshot
    assert "import app" not in snapshot


def test_phase16_shadow_telemetry_preserves_diagnostic_only_contract() -> None:
    telemetry = (
        _backend_root() / "aether_vnext" / "shadow_cutover_telemetry.py"
    ).read_text(encoding="utf-8")

    for stage in (
        "UNIVERSE",
        "WATCH",
        "FIRE",
        "SIZE",
        "READY",
        "ORDER",
        "OPEN",
    ):
        assert f'"{stage}"' in telemetry

    assert "first_killer_distribution" in telemetry
    assert "dwell_time" in telemetry
    assert "would_have_passed_prior_policy" in telemetry
    assert '"may_create_orders": False' in telemetry
    assert '"trade_influence_enabled": False' in telemetry
    assert "shadow comparison cannot create an order" in telemetry
    assert "shadow comparison cannot influence trading" in telemetry


def test_phase16_source_tree_has_no_unresolved_implementation_markers() -> None:
    backend = _backend_root()
    phase16_files = (
        backend / "app" / "vnext_shadow.py",
        backend / "aether_vnext" / "shadow_floor_snapshot.py",
        backend / "aether_vnext" / "shadow_cutover_telemetry.py",
        backend / "aether_vnext" / "operator_floor_api.py",
    )
    for path in phase16_files:
        source = path.read_text(encoding="utf-8")
        assert "NotImplemented" not in source
        assert "TODO" not in source
        assert "FIXME" not in source


def test_phase16_closeout_document_keeps_runtime_evidence_gate_open() -> None:
    closeout = (
        _repo_root() / "docs" / "AETHER_PHASE16_CLOSEOUT.md"
    ).read_text(encoding="utf-8")

    assert "INTERNAL SHADOW BUILD CLOSEOUT CANDIDATE" in closeout
    assert "RUNTIME SHADOW EVIDENCE PENDING" in closeout
    assert "PAPER ONLY / LIVE HARD BLOCKED" in closeout
    assert "No unit test or synthetic fixture may be substituted" in closeout
    assert "Phase 17 — Full Swap-Out" in closeout
