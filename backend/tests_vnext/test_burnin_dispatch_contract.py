from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BURNIN = ROOT / ".github" / "workflows" / "aether-vnext-burnin.yml"
VNEXT_CI = ROOT / ".github" / "workflows" / "aether-vnext-ci.yml"


def test_burnin_dispatch_is_same_repo_label_gated_and_environment_protected() -> None:
    source = BURNIN.read_text(encoding="utf-8")

    assert "pull_request:" in source
    assert "- labeled" in source
    assert "pull_request_target" not in source

    assert "github.event.pull_request.head.repo.full_name == github.repository" in source
    assert "github.event.pull_request.head.ref == 'aether-vnext-swapout'" in source
    assert "aether-vnext-burnin-preflight-approved" in source
    assert "aether-vnext-kraken-probe-approved" in source
    assert "aether-vnext-burnin-start-approved" in source

    assert "environment: aether-vnext-burnin" in source
    assert "github.event.pull_request.head.sha" in source
    assert "Verify checked-out commit identity" in source
    assert "AETHER_VNEXT_BURNIN_DATABASE_URL" in source
    assert "AETHER_VNEXT_BURNIN_POSTGRESQL_CONNECTIONSTRING" in source
    assert "AETHER_VNEXT_RUNTIME_BINDINGS_JSON" in source
    assert "aether_vnext_registry_bindings.py" in source
    assert "--require-complete" in source
    assert "--require-implemented-source" in source
    assert "--require-implemented-calendar" in source
    assert "aether_vnext_kraken_market_probe.py" in source
    assert "--assets btc,eth" in source
    assert "--require-executable" in source

    assert "routes_json" not in source
    assert "--routes-json" not in source
    assert "aether_vnext_burnin_preflight.py" in source
    assert "aether_vnext_burnin_start.py" in source


def test_contract_ci_contains_no_secret_bearing_manual_burnin_job() -> None:
    source = VNEXT_CI.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in source
    assert "burnin-preflight-manual" not in source
    assert "AETHER_VNEXT_BURNIN_DATABASE_URL" not in source
    assert "secrets." not in source
