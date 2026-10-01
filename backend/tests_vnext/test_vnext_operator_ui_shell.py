from __future__ import annotations

from pathlib import Path


def test_vnext_ui_restores_familiar_operator_shell_without_legacy_routes() -> None:
    root = Path(__file__).resolve().parents[2]
    page = (root / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (root / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")

    assert 'const operatorPath = "/api/v1/vnext/operator"' in page
    assert 'const discoveryPath = "/api/v1/vnext/discovery-runtime"' in page
    assert "function BottomDock" in page
    assert "function AppMenu" in page
    assert "function LiveTradesView" in page
    assert "function BlotterView" in page
    assert "function SettingsView" in page
    assert "function BoothView" in page
    assert "function PipelineView" in page
    assert "function ProviderDiscoveryBoard" in page
    assert "function ProviderFocusCard" in page
    assert "function feedClassLabel" in page
    assert "PUBLIC REF · DELAYED" in page
    assert "REFERENCE FEED" in page
        assert "SCOUT RECEIVED" in page
    assert "Scout Intake" in page
    assert "function pipelineBottleneck" in page
    assert "function DesktopCommandCenter" in page
    assert "function MobileCommandStrip" in page
    assert "function CompactBlotterPreview" in page
    assert "AETHER PROP FIRM" in page
    assert "NATURAL SETUPS ONLY" in page
    assert "LIVE BLOCKED" in page
    assert "legacy" not in page.lower() or "legacy trading state" in page.lower()

    for label in ("Floor", "Pipeline", "Assets", "Live", "Blotter", "Booth"):
        assert label in page

    assert ".bottomDock" in css
    assert ".appMenu" in css
    assert ".blotterTable" in css
    assert ".activityFeed" in css
    assert ".bankStrip" in css
    assert ".pipelineFlow" in css
    assert ".pipelinePressure" in css
    assert ".governorGate" in css
    assert ".providerDiscoveryFunnel" in css
    assert ".providerFocusGrid" in css
    assert ".providerFeedClass" in css
    assert ".providerTop100" in css
    assert ".providerFeedLegend" in css
        assert ".focusReceived" in css
    assert ".desktopCommandCenter" in css
    assert ".desktopCommandGrid" in css
    assert ".mobileCommandStrip" in css
    assert "@media (max-width: 900px)" in css
