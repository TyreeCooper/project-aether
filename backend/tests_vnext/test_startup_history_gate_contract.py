from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_startup_loader_includes_history_service_without_new_endpoint() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert '["history", "Historical Services"]' in page
    assert 'key === "history" ? data.strategy : data[key]' in page
    assert 'key === "history" ? endpointHealth.strategy : endpointHealth[key]' in page
    assert 'state:"WARMING", detail:"awaiting first history service result"' in page


def test_history_loader_gate_accepts_asset_holds_without_blocking_console_forever() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "readyObserved && heldObserved" in page
    assert "history service observed" in page
    assert "Historical Services reports service readiness without requiring every asset to be history-ready." in page


def test_history_loader_gate_is_not_startup_recoverable_component() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert 'const STARTUP_RECOVERABLE = new Set(["ingress","discovery","tape","strategy"]);' in page
