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
    assert "for attempt in $(seq 1 24); do" in workflow
    assert 'build.get("source_revision") == os.environ["EXPECTED_SHA"]' in workflow
    assert 'test "$revision_ready" = "1"' in workflow

    health_gate = workflow.index("health_ready=0")
    revision_gate = workflow.index("revision_ready=0")
    ingress_gate = workflow.index("ingress_ready=0")
    strategy_gate = workflow.index("strategy_ready=0")
    assert health_gate < revision_gate < ingress_gate < strategy_gate
    assert "Diagnose Azure runtime on activation failure" in workflow
    assert "az webapp log startup show" in workflow


def test_activation_proves_strategy_monitor_ui_after_exact_head_cutover() -> None:
    workflow = _workflow()

    assert "ui_ready=0" in workflow
    assert 'grep -q "Live Strategy Monitor" /tmp/index.html' in workflow
    assert 'grep -q "AUTONOMOUS PAPER ENGINE" /tmp/index.html' in workflow
    assert '"$base/vnext/"' in workflow
    assert '"$base/" || true' not in workflow
    assert 'test "$ui_ready" = "1"' in workflow
    assert "/tmp/index.html" in workflow


def test_activation_keeps_prototype_safety_invariants() -> None:
    workflow = _workflow()

    assert "AETHER_VNEXT_RUNTIME_ONLY=true" in workflow
    assert "AETHER_VNEXT_KRAKEN_INGRESS_ENABLED=true" in workflow
    assert "AETHER_VNEXT_PROTOTYPE_TRADING_ENABLED=true" in workflow
    assert 'body.get("paper_mode") is True' in workflow
    assert 'body.get("live_blocked") is True' in workflow
    assert 'result.get("phase18_evidence") is False' in workflow
    assert 'row.get("forward_paper_observation_recorded") is True' in workflow
    assert 'int(result.get("forward_paper_observation_count") or 0)' in workflow
    assert ">= len(no_setup)" in workflow
    assert "aether-vnext-nonprod" in workflow
    assert 'test "$app" != "aether-prod-api"' in workflow
