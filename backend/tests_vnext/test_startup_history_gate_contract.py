from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_background_runtime_readiness_includes_history_service_without_blocking_shell() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert 'const BACKGROUND_RUNTIME_GATES = [' in page
    assert '["history", "Historical Services"]' in page
    assert 'key==="history"?data.strategy:data[key]' in page
    assert 'key==="history"?endpointHealth.strategy:endpointHealth[key]' in page
    assert 'state:"WARMING", detail:"awaiting first history service result"' in page
    assert "BACKGROUND_RUNTIME_GATES.every" not in page


def test_shell_release_waits_only_for_authoritative_vnext_safety_contract() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "function startupSafetyState" in page
    assert 'payload?.runtime === "vnext"' in page
    assert "payload?.paper_mode === true" in page
    assert "payload?.live_blocked === true" in page
    assert 'if(startupSafetyState(payload,"live").ready) setShellReady(true);' in page
    assert "Only the authoritative vNext PAPER ONLY / LIVE BLOCKED safety contract can hold this screen." in page


def test_telemetry_loads_independently_after_shell_release() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "for(const [key,path] of telemetry)" in page
    assert "getJson(path)" in page
    assert "slow telemetry must never serialize startup" in page
    assert "Market ingress, discovery, Market Fabric, history, strategy, operator telemetry and maintenance continue warming in the background" in page


def test_history_readiness_accepts_asset_holds_without_blocking_console() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "readyObserved && heldObserved" in page
    assert "history service observed" in page


def test_history_service_is_not_startup_recoverable_component() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert 'const STARTUP_RECOVERABLE = new Set(["ingress","discovery","tape","strategy"]);' in page


def test_background_recovery_continues_after_shell_opens() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    recovery_block = page.split("postStartupRecovery(active.key)", 1)[0].rsplit("useEffect(()=>{", 1)[-1]
    assert "if(shellReady)return" not in recovery_block
    assert "STARTUP_RECOVERABLE.has(gate.key)" in recovery_block
