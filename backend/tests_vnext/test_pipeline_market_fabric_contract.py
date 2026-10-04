from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pipeline_presents_exact_seventeen_canonical_gates() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    start = page.index("const PIPELINE_GATE_BLUEPRINT = [")
    end = page.index("];", start)
    blueprint = page[start:end]

    expected = [
        "Discovery Admission",
        "Commissioning",
        "Work Scheduler",
        "Executable Ingress",
        "History & Warm-Up",
        "Closed-Bar Evaluation",
        "Scout Admission",
        "Sniper Fire",
        "Risk / Size",
        "Clerk",
        "Portfolio Reserve",
        "Paper Submit",
        "Fill Guard",
        "Exit Management",
        "Close Reservation",
        "Paper Close Submit",
        "Close Fill",
    ]
    for number, label in enumerate(expected, start=1):
        assert f"number: {number}," in blueprint
        assert f'label: "{label}"' in blueprint

    assert blueprint.count("number: ") == 17
    assert 'label: "FLAT / BLOTTER"' not in blueprint
    assert "TERMINAL STATE — NOT GATE 18" in page


def test_pipeline_wires_market_fabric_dual_truth_into_gate_four() -> None:
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")

    assert "marketFabric={marketFabric}" in page
    assert 'eyebrow="MARKET FABRIC → GATE 04"' in page
    assert "consensus_can_replace_executable_price === false" in page
    assert "Witness sources provide corroboration and market intelligence only." in page
    assert "never overwrite route truth" in page
