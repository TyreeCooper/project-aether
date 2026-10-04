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
    canonical_proof = workflow.index("Prove the canonical five-layer runtime rather than the quarantined")
    assert revision_gate < health_gate < ui_gate < canonical_proof
    assert "Diagnose Azure runtime on activation failure" in workflow
    assert "az webapp log startup show" in workflow


def test_activation_proves_ui_after_exact_head_cutover() -> None:
    workflow = _workflow()
    assert "ui_ready=0" in workflow
    assert '[ -s /tmp/index.html ]' in workflow
    assert 'grep -q "Command Center" /tmp/index.html' not in workflow
    assert '"$base/vnext/"' in workflow
    assert 'test "$ui_ready" = "1"' in workflow
    assert "/tmp/index.html" in workflow


def test_activation_keeps_sandbox_safety_and_quarantines_legacy_authority() -> None:
    workflow = _workflow()
    assert "AETHER_VNEXT_ENVIRONMENT=sandbox" in workflow
    assert "AETHER_VNEXT_KRAKEN_INGRESS_ENABLED=false" in workflow
    assert "AETHER_VNEXT_SANDBOX_TRADING_ENABLED=false" in workflow
    assert "AETHER_VNEXT_TAPE_ENABLED=false" in workflow
    assert 'body.get("paper_mode") is True' in workflow
    assert 'body.get("live_blocked") is True' in workflow
    assert 'fabric.get("architecture") == "AETHER_MARKET_TRUTH_V1"' in workflow
    assert '"legacy_authority":{' in workflow
    assert "/tmp/pipeline-health.json" in workflow
    assert "aether-vnext-nonprod" in workflow
    assert 'test "$app" != "aether-prod-api"' in workflow


def test_activation_does_not_require_live_market_to_be_executable_for_deployment() -> None:
    workflow = _workflow()
    marker = "Prove the canonical five-layer runtime rather than the quarantined"
    runtime_section = workflow[workflow.index(marker):workflow.index("Refresh Azure login for failure diagnostics")]
    assert 'executable.get("state") in {"EXECUTABLE","STALE","NOT_OBSERVED"}' in runtime_section
    assert 'if executable.get("state") != "EXECUTABLE":' in runtime_section
    assert 'executable.get("bid") is None and executable.get("ask") is None' in runtime_section
    assert 'assert executable.get("state") == "EXECUTABLE"' not in runtime_section
    assert "pipeline-health.json" in runtime_section


def test_activation_requires_canonical_runtime_progress_not_legacy_cycles() -> None:
    workflow = _workflow()
    assert 'b.get("last_progress_at_utc") != a.get("last_progress_at_utc")' in workflow
    assert 'b.get("executable_packet_count")' in workflow
    assert 'b.get("witness_packet_count")' in workflow
    assert "assert progressed, (a,b)" in workflow
    assert "/tmp/market-fabric-first.json" in workflow
    assert "/tmp/market-fabric-second.json" in workflow
