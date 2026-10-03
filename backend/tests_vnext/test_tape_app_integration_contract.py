from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_operator_console_surfaces_tape_across_runtime_views() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "<span>TAPE</span>" in page
    assert "Tape-governed seeds" in page
    assert "MARKET TRUTH DEPENDENCY" in page
    assert "Tape independence" in page
    assert 'label="Tape"' in page
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
    assert 'assert_moving("tape"' in workflow
    assert 'row.get("state") == "FULL"' in workflow
    assert "/tmp/tape-second.json" in workflow
