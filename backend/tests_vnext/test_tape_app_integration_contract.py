from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_operator_console_surfaces_canonical_execution_and_evidence_axes() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "<span>MARKET TRUTH</span>" in page
    assert "<span>EXECUTION</span>" in page
    assert "<span>EVIDENCE</span>" in page
    assert "<span>LEGACY AUTHORITY</span>" in page
    assert "Human-route book — exactly as printed" in page
    assert "NO_WITNESS" in page
    assert "Market Fabric execution universe" in page
    assert "QUARANTINED" in page


def test_activation_proves_canonical_market_truth_runtime_continuity() -> None:
    workflow = (
        ROOT
        / ".github"
        / "workflows"
        / "aether-vnext-activate-paper-prototype.yml"
    ).read_text(encoding="utf-8")
    assert "AETHER_VNEXT_TAPE_ENABLED=false" in workflow
    assert "/api/v1/vnext/market-fabric" in workflow
    assert "/tmp/market-fabric-first.json" in workflow
    assert "/tmp/market-fabric-second.json" in workflow
    assert '"NO_WITNESS","CONTESTED","DIVERGED","SINGLE_SOURCE","DEGRADED","FULL"' in workflow
    assert '"legacy_authority":"QUARANTINED"' in workflow
