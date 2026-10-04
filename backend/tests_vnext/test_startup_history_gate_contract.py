from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_background_runtime_readiness_uses_canonical_market_truth() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert 'const BACKGROUND_RUNTIME_GATES = [' in page
    assert '["marketFabric", "Canonical Market Truth"]' in page
    assert '["discovery", "Provider Discovery"]' in page
    assert '["ingress", "Executable Ingress"]' not in page
    assert '["tape", "Market Fabric"]' not in page
    assert '["strategy", "Strategy Runtime"]' not in page
    assert '["history", "Historical Services"]' not in page


def test_shell_release_waits_only_for_authoritative_vnext_safety_contract() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "function startupSafetyState" in page
    assert 'payload?.runtime === "vnext"' in page
    assert "payload?.paper_mode === true" in page
    assert "payload?.live_blocked === true" in page
    assert 'if(startupSafetyState(payload,"live").ready) setShellReady(true);' in page


def test_canonical_market_truth_warms_independently_after_shell_release() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert 'payload?.architecture === "AETHER_MARKET_TRUTH_V1"' in page
    assert "Legacy ingress, Tape and strategy authority are quarantined during first proof." in page
    assert "for(const [key,path] of telemetry)" in page


def test_only_discovery_is_startup_recoverable_from_ui() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert 'const STARTUP_RECOVERABLE = new Set(["discovery"]);' in page
    recovery_block = page.split("postStartupRecovery(active.key)", 1)[0].rsplit("useEffect(()=>{", 1)[-1]
    assert "STARTUP_RECOVERABLE.has(gate.key)" in recovery_block
