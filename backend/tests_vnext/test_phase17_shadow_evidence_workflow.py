from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_shadow_evidence_workflow_is_manual_protected_and_branch_scoped() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-shadow-evidence.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "github.ref_name == 'aether-vnext-swapout'" in workflow
    assert "environment: aether-vnext-burnin" in workflow
    assert 'test "$GITHUB_REF_NAME" = "aether-vnext-swapout"' in workflow


def test_shadow_evidence_workflow_requires_https_and_refuses_production_target() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-shadow-evidence.yml"
    ).read_text(encoding="utf-8")

    assert "base_url must use https." in workflow
    assert "aether-prod-api" in workflow
    assert "Production app target is forbidden for shadow evidence." in workflow
    assert "aether_vnext_shadow_http_probe.py" in workflow


def test_shadow_evidence_workflow_has_no_protected_secret_references() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-shadow-evidence.yml"
    ).read_text(encoding="utf-8")

    assert "secrets." not in workflow
    assert "AETHER_VNEXT_DATABASE_URL" not in workflow
    assert "azure/login" not in workflow
