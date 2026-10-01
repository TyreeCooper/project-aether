from __future__ import annotations

from pathlib import Path


def test_vnext_ui_restores_familiar_operator_shell_without_legacy_routes() -> None:
    root = Path(__file__).resolve().parents[2]
    page = (root / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (root / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")

    assert 'const operatorPath = "/api/v1/vnext/operator"' in page
    assert "function BottomDock" in page
    assert "function AppMenu" in page
    assert "function LiveTradesView" in page
    assert "function BlotterView" in page
    assert "function SettingsView" in page
    assert "function BoothView" in page
    assert "NATURAL SETUPS ONLY" in page
    assert "LIVE BLOCKED" in page
    assert "legacy" not in page.lower() or "legacy trading state" in page.lower()

    for label in ("Floor", "Assets", "Live", "Blotter", "Booth"):
        assert label in page

    assert ".bottomDock" in css
    assert ".appMenu" in css
    assert ".blotterTable" in css
    assert ".activityFeed" in css
    assert ".bankStrip" in css
