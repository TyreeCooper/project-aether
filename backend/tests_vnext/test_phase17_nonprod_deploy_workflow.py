from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workflow() -> str:
    return (
        _repo_root()
        / ".github"
        / "workflows"
        / "aether-vnext-nonprod-deploy.yml"
    ).read_text(encoding="utf-8")


def test_nonprod_deploy_workflow_is_manual_and_exact_head_gated() -> None:
    workflow = _workflow()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "environment: aether-vnext-burnin" not in workflow
    assert "github.ref_name == 'aether-vnext-swapout'" in workflow
    assert "expected_head_sha:" in workflow
    assert 'test "$actual" = "$EXPECTED_HEAD_SHA"' in workflow
    assert 'test "$actual" = "$GITHUB_SHA"' in workflow


def test_nonprod_deploy_workflow_is_hard_bound_to_dedicated_vnext_app() -> None:
    workflow = _workflow()

    assert 'app_name="aether-vnext-nonprod"' in workflow
    assert 'resource_group="aether-rg"' in workflow
    assert 'if [ "$app_name" = "aether-prod-api" ]' in workflow
    assert "Production target is forbidden." in workflow
    assert "aether-vnext-nonprod-*.azurewebsites.net" in workflow
    assert "az webapp show" in workflow
    assert "slot-name:" not in workflow


def test_nonprod_deploy_workflow_verifies_vnext_paper_surface() -> None:
    workflow = _workflow()

    assert 'NEXT_PUBLIC_API_BASE: ""' in workflow
    assert "/vnext/" in workflow
    assert "/api/v1/vnext/floor" in workflow
    assert 'body.get("paper_mode") is True' in workflow
    assert 'body.get("live_blocked") is True' in workflow
    assert 'mode.get("paper_only") is True' in workflow
    assert 'mode.get("live_blocked") is True' in workflow
    assert 'build.get("source_revision") == os.environ["EXPECTED_SHA"]' in workflow
    assert 'test "$code" = "405"' in workflow


def test_nonprod_deploy_workflow_uses_dedicated_vnext_oidc_identity() -> None:
    workflow = _workflow()

    assert "azure/login@v2" in workflow
    assert "azure/webapps-deploy@v3" in workflow
    assert "AZUREAPPSERVICE_CLIENTID_E2CE53939F2D406CBA8FB39DB4948C7B" in workflow
    assert "AZUREAPPSERVICE_TENANTID_0E83D5CA9CF543228DA7FA7818D7C998" in workflow
    assert "AZUREAPPSERVICE_SUBSCRIPTIONID_B530D2ECBF5549A39B4758868409068A" in workflow
    assert "AZUREAPPSERVICE_CLIENTID_530CF31F9C844B6BBFDBCED78DB6E9E4" not in workflow
