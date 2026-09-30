from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "aether-vnext-azure-target-discovery.yml"
)


def test_azure_target_discovery_is_label_gated_and_environment_protected() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in source
    assert "- labeled" in source
    assert "pull_request_target" not in source
    assert "github.event.pull_request.head.repo.full_name == github.repository" in source
    assert "github.event.pull_request.head.ref == 'aether-vnext-swapout'" in source
    assert "aether-vnext-azure-discovery-approved" in source
    assert "environment: aether-vnext-burnin" in source
    assert "github.event.pull_request.head.sha" in source


def test_azure_target_discovery_is_read_only_and_excludes_production() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "az webapp list" in source
    assert "az webapp deployment slot list" in source
    assert '"read_only": True' in source
    assert '"production_target_excluded": True' in source
    assert 'name != "aether-prod-api"' in source
    assert 'slot_name.lower() == "production"' in source
    assert 'aether-prod-api.azurewebsites.net' in source

    forbidden = (
        "az webapp create",
        "az webapp delete",
        "az webapp deployment source",
        "az webapp config appsettings",
        "azure/webapps-deploy",
        "AETHER_VNEXT_DATABASE_URL",
        "AETHER_VNEXT_RUNTIME_BINDINGS_JSON",
    )
    for value in forbidden:
        assert value not in source


def test_azure_target_discovery_reuses_existing_oidc_identity_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "azure/login@v2" in source
    assert "AZUREAPPSERVICE_CLIENTID_530CF31F9C844B6BBFDBCED78DB6E9E4" in source
    assert "AZUREAPPSERVICE_TENANTID_C8115A17EE8945578F04F145FD68F4CE" in source
    assert "AZUREAPPSERVICE_SUBSCRIPTIONID_AD212BE4448A497488FE91D5E47F27B6" in source
    assert "secrets." in source
    assert "appsettings list" not in source
    assert "connection-string" not in source
