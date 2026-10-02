from __future__ import annotations

from pathlib import Path


def test_vnext_ui_uses_professional_multi_page_operations_shell() -> None:
    root = Path(__file__).resolve().parents[2]
    page = (root / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    css = (root / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")

    for endpoint in ('const operatorPath = "/api/v1/vnext/operator"', 'const discoveryPath = "/api/v1/vnext/discovery-runtime"', 'const maintenancePath = "/api/v1/vnext/maintenance"'):
        assert endpoint in page

    for view in ("Command Center", "Markets", "Pipeline", "Trading Floor", "Positions", "Blotter", "Maintenance", "Settings"):
        assert view in page

    for component in ("function CommandCenter", "function Markets", "function Pipeline", "function TradingFloor", "function Positions", "function Blotter", "function Maintenance", "function Settings", "function RuntimeStrip"):
        assert component in page

    assert "PAPER ACTIVE" in page
    assert "LIVE BLOCKED" in page
    assert "Autonomous Market Operations" in page
    assert "Provider universe" in page
    assert "Institutional pipeline flow map" in page

    for forbidden in ('assetId="btc"', 'assetId="eth"', "Top 12 Attention", "function BottomDock", "function AppMenu", "Prototype Stations"):
        assert forbidden not in page

    for selector in (".sidebar", ".workspace", ".runtimeStrip", ".marketTable", ".flowMap", ".tradeMatrix", ".positionGrid", ".incidentTable", ".controlGrid"):
        assert selector in css

    assert "@media(max-width:900px)" in css
