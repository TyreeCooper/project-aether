from __future__ import annotations

from pathlib import Path


def _workflow() -> str:
    root = Path(__file__).resolve().parents[2]
    return (
        root
        / ".github"
        / "workflows"
        / "aether-vnext-prototype-restart-recovery.yml"
    ).read_text(encoding="utf-8")


def test_restart_recovery_is_protected_and_nonproduction_only() -> None:
    workflow = _workflow()

    assert "environment: aether-vnext-burnin" in workflow
    assert "id-token: write" in workflow
    assert 'app="aether-vnext-nonprod"' in workflow
    assert 'test "$app" != "aether-prod-api"' in workflow
    assert 'test "$app_name" != "aether-prod-api"' in workflow
    assert "azure/webapps-deploy" not in workflow


def test_restart_recovery_proves_real_process_restart_same_revision() -> None:
    workflow = _workflow()

    assert "Capture pre-restart PAPER state" in workflow
    assert "az webapp restart" in workflow
    assert "Prove post-restart recovery" in workflow
    assert 'build.get("source_revision") == os.environ["EXPECTED_REVISION"]' in workflow
    assert 'str(body.get("runtime_started_at_utc") or "") != os.environ["EXPECTED_STARTED"]' in workflow
    assert 'floor.get("runtime_started_at_utc") != pre["runtime_started_at_utc"]' in workflow


def test_restart_recovery_preserves_paper_state_and_safety() -> None:
    workflow = _workflow()

    assert "aether-prototype-new-system-test-001" in workflow
    assert "10000.0" in workflow
    assert "post_blotter >= int(pre[\"blotter_trade_count\"])" in workflow
    assert "post_observations >= int(pre[\"forward_paper_observation_count\"])" in workflow
    assert 'result.get("phase18_evidence") is False' in workflow
    assert 'result.get("paper_only") is True' in workflow
    assert 'result.get("live_blocked") is True' in workflow
    assert "prototype_service_restart_recovery" in workflow
    assert "actions/upload-artifact@v4" in workflow
