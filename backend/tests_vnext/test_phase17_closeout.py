from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_phase17_modules_have_no_direct_runtime_activation_side_effect() -> None:
    root = _backend_root() / "aether_vnext"
    files = (
        root / "full_swap_readiness.py",
        root / "full_swap_plan.py",
        root / "full_swap_rollback.py",
        root / "full_swap_status.py",
    )

    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "engine.start_loop" not in source
        assert "engine.shutdown" not in source
        assert "webapps-deploy" not in source
        assert "azure/login" not in source
        assert "from app" not in source
        assert "import app" not in source


def test_phase17_readiness_keeps_runtime_shadow_proof_as_hard_gate() -> None:
    source = (
        _backend_root() / "aether_vnext" / "full_swap_readiness.py"
    ).read_text(encoding="utf-8")

    assert "phase16_runtime_shadow_verified" in source
    assert "canonical_vnext_book_reconciled" in source
    assert "restart_recovery_verified" in source
    assert "rollback_path_verified" in source
    assert "legacy_runtime_authority_retirable" in source
    assert "live_execution_authorized=False" in source


def test_phase17_plan_and_rollback_preserve_offline_reconciliation_safety() -> None:
    backend = _backend_root() / "aether_vnext"
    plan = (backend / "full_swap_plan.py").read_text(encoding="utf-8")
    rollback = (backend / "full_swap_rollback.py").read_text(encoding="utf-8")

    assert 'restart_state="OFFLINE"' in plan
    assert "reconciliation_required_before_arm=True" in plan
    assert "activation_side_effect_performed=False" in plan

    assert 'start_state="OFFLINE"' in rollback
    assert "reconciliation_required_before_arm=True" in rollback
    assert "automatic_rearm_allowed=False" in rollback
    assert "operator_confirmation_required=True" in rollback
    assert "rollback_side_effect_performed=False" in rollback


def test_phase17_status_does_not_claim_actual_swap_from_a_plan() -> None:
    source = (
        _backend_root() / "aether_vnext" / "full_swap_status.py"
    ).read_text(encoding="utf-8")

    assert '"runtime_authority_changed": False' in source
    assert '"legacy_runtime_authority_retired_actual": False' in source
    assert '"may_switch_runtime": False' in source
    assert '"may_start_runtime": False' in source
    assert '"may_enable_live": False' in source


def test_phase17_source_tree_has_no_unresolved_implementation_markers() -> None:
    root = _backend_root() / "aether_vnext"
    for name in (
        "full_swap_readiness.py",
        "full_swap_plan.py",
        "full_swap_rollback.py",
        "full_swap_status.py",
    ):
        source = (root / name).read_text(encoding="utf-8")
        assert "NotImplemented" not in source
        assert "TODO" not in source
        assert "FIXME" not in source


def test_phase17_closeout_document_keeps_actual_activation_open() -> None:
    closeout = (
        _repo_root() / "docs" / "AETHER_PHASE17_CLOSEOUT.md"
    ).read_text(encoding="utf-8")

    assert "REPOSITORY CONTROL-PLANE PREP CLOSEOUT CANDIDATE" in closeout
    assert "RUNTIME ACTIVATION BLOCKED" in closeout
    assert "PAPER ONLY / LIVE HARD BLOCKED" in closeout
    assert "has **not**" in closeout
    assert "runtime authority actually changes" in closeout
    assert "Phase 18 — Forward Paper Evidence remains separately" in closeout
