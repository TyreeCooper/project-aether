from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_operator_console_surfaces_tape_across_runtime_views() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "<span>WITNESS FABRIC</span>" in page
    assert "Market Fabric evidence policy" in page
    assert "MARKET FABRIC → GATE 04" in page
    assert "Dual-truth market authority" in page
    assert "NEVER OVERWRITE" in page
    assert "Market Fabric independence" in page
    assert 'label="Market Fabric"' in page
    assert "pipelineRuntimeState(ingress, discovery, tape, strategy" in page


def test_activation_proves_tape_runtime_continuity_and_full_consensus() -> None:
    workflow = (
        ROOT
        / ".github"
        / "workflows"
        / "aether-vnext-activate-paper-prototype.yml"
    ).read_text(encoding="utf-8")
    assert "AETHER_VNEXT_TAPE_ENABLED=true" in workflow
    assert "/api/v1/vnext/tape" in workflow
    assert 'movement("tape", tape_first_runtime, tape_second_runtime)' in workflow
    assert 'row.get("state") == "FULL"' in workflow
    assert "/tmp/tape-second.json" in workflow
