from __future__ import annotations

from pathlib import Path


def _workflow() -> str:
    root = Path(__file__).resolve().parents[2]
    return (
        root
        / ".github"
        / "workflows"
        / "aether-vnext-activate-paper-prototype.yml"
    ).read_text(encoding="utf-8")


def test_activation_waits_for_exact_revision_before_runtime_proof() -> None:
    workflow = _workflow()

    assert "revision_ready=0" in workflow
    assert "for attempt in $(seq 1 36); do" in workflow
    assert 'build.get("source_revision") == os.environ["EXPECTED_SHA"]' in workflow
    assert 'test "$revision_ready" = "1"' in workflow

    revision_gate = workflow.index("revision_ready=0")
    health_gate = workflow.index("health_ready=0")
    ui_gate = workflow.index("ui_ready=0")
    pipeline_capture = workflow.index("Deployment success is intentionally separate from live pipeline health")
    assert revision_gate < health_gate < ui_gate < pipeline_capture
    assert "Diagnose Azure runtime on activation failure" in workflow
    assert "az webapp log startup show" in workflow


def test_activation_proves_strategy_monitor_ui_after_exact_head_cutover() -> None:
    workflow = _workflow()

    assert "ui_ready=0" in workflow
    assert 'grep -q "Command Center" /tmp/index.html' in workflow
    assert 'grep -q "Autonomous Market Operations" /tmp/index.html' in workflow
    assert '"$base/vnext/"' in workflow
    assert '"$base/" || true' not in workflow
    assert 'test "$ui_ready" = "1"' in workflow
    assert "/tmp/index.html" in workflow


def test_activation_keeps_sandbox_safety_invariants() -> None:
    workflow = _workflow()

    assert "AETHER_VNEXT_ENVIRONMENT=sandbox" in workflow
    assert "AETHER_VNEXT_KRAKEN_INGRESS_ENABLED=true" in workflow
    assert "AETHER_VNEXT_SANDBOX_TRADING_ENABLED=true" in workflow
    assert 'body.get("paper_mode") is True' in workflow
    assert 'body.get("live_blocked") is True' in workflow
    assert '"deployment_health": "GREEN"' in workflow
    assert '"pipeline_health": "DEGRADED"' in workflow
    assert "/tmp/pipeline-health.json" in workflow
    assert "aether-vnext-nonprod" in workflow
    assert 'test "$app" != "aether-prod-api"' in workflow


def test_activation_does_not_fail_deployment_on_live_pipeline_condition() -> None:
    workflow = _workflow()

    marker = "Deployment success is intentionally separate from live pipeline health"
    assert marker in workflow
    runtime_section = workflow[workflow.index(marker):workflow.index("Refresh Azure login for failure diagnostics")]
    assert "ingress_ready=0" not in runtime_section
    assert "strategy_ready=0" not in runtime_section
    assert 'result["pipeline_health"]="BLOCKED"' in runtime_section
    assert "pipeline-health.json" in runtime_section



def test_activation_accepts_fresh_recovery_progress_but_not_static_prior_error() -> None:
    workflow = _workflow()

    assert "recovering_from_previous_error" in workflow
    assert 'b["progress_state"] == "running"' in workflow
    assert 'b["progress_heartbeat"] != a["progress_heartbeat"]' in workflow
    assert 'assert after.get("last_error") is None or recovering, after' in workflow
    assert 'assert after.get("last_error") is None, after' not in workflow
