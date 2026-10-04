from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_current_head_readiness_uses_existing_approved_label_and_protected_environment() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-current-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "types:" in workflow
    assert "- labeled" in workflow
    assert "aether-vnext-burnin-readiness-approved" in workflow
    assert "environment: aether-vnext-burnin" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "aether-vnext-swapout" in workflow


def test_current_head_readiness_is_read_only_and_revision_traceable() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-current-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "aether_vnext_burnin_readiness.py" in workflow
    assert "source_revision" in workflow
    assert 'body["read_only"] = True' in workflow
    assert "aether_vnext_burnin_start.py" not in workflow
    assert "alembic upgrade" not in workflow
    assert "azure/webapps-deploy" not in workflow
    assert "start_campaign" not in workflow


def test_current_head_readiness_cancels_superseded_readiness_requests_only() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-current-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "group: aether-vnext-current-readiness-" in workflow
    assert "cancel-in-progress: true" in workflow
