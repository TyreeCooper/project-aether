from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_nonprod_deploy_workflow_is_manual_and_environment_protected() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-nonprod-deploy.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "environment: aether-vnext-burnin" in workflow
    assert "github.ref_name == 'aether-vnext-swapout'" in workflow
    assert "expected_head_sha:" in workflow


def test_nonprod_deploy_workflow_refuses_production_and_verifies_vnext() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-nonprod-deploy.yml"
    ).read_text(encoding="utf-8")

    assert "Direct deployment to aether-prod-api Production is forbidden." in workflow
    assert "Production hostname is forbidden." in workflow
    assert 'NEXT_PUBLIC_API_BASE: ""' in workflow
    assert "/vnext/" in workflow
    assert "/api/v1/vnext/floor" in workflow
    assert 'mode.get("paper_only") is True' in workflow
    assert 'mode.get("live_blocked") is True' in workflow
    assert 'test "$code" = "405"' in workflow


def test_nonprod_deploy_workflow_uses_existing_azure_oidc_identity_only() -> None:
    workflow = (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-nonprod-deploy.yml"
    ).read_text(encoding="utf-8")

    assert "azure/login@v2" in workflow
    assert "azure/webapps-deploy@v3" in workflow
    assert "AZUREAPPSERVICE_CLIENTID_530CF31F9C844B6BBFDBCED78DB6E9E4" in workflow
    assert "AZUREAPPSERVICE_TENANTID_C8115A17EE8945578F04F145FD68F4CE" in workflow
    assert "AZUREAPPSERVICE_SUBSCRIPTIONID_AD212BE4448A497488FE91D5E47F27B6" in workflow
