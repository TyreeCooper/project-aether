from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_nonprod_package_workflow_builds_one_same_origin_azure_artifact() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-nonprod-package.yml"
    ).read_text(encoding="utf-8")

    assert "AETHER vNext Nonprod Package" in workflow
    assert "Nonprod packaging refuses manual execution from main." in workflow
    assert 'NEXT_PUBLIC_API_BASE: ""' in workflow
    assert 'NEXT_PUBLIC_AETHER_FLOOR_PATH: "/api/v1/vnext/floor"' in workflow
    assert "frontend/out/." in workflow
    assert "backend/app/vnext_ui/" in workflow
    assert "aether-vnext-nonprod.zip" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_nonprod_package_workflow_has_no_deployment_or_secret_authority() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-nonprod-package.yml"
    ).read_text(encoding="utf-8")

    assert "azure/login" not in workflow
    assert "azure/webapps-deploy" not in workflow
    assert "secrets." not in workflow
    assert "aether-prod-api" not in workflow
