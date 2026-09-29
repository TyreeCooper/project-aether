from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_phase15_frontend_contains_complete_unified_floor_composition() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    for required in (
        "Unified Firm Floor",
        "Full Universe",
        "Top 12 Attention",
        "Seat Queues",
        "Open Position Cockpits",
        "Inspection Drawer",
        "PAPER ONLY",
        "LIVE BLOCKED",
        "/api/v1/vnext/floor",
    ):
        assert required in page


def test_phase15_frontend_exposes_no_mutation_transport() -> None:
    page = (_repo_root() / "frontend" / "app" / "page.js").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        'method: "POST"',
        'method: "PUT"',
        'method: "PATCH"',
        'method: "DELETE"',
        "createOrder",
        "placeOrder",
        "resetGovernor",
        "mutateRoute",
    ):
        assert forbidden not in page


def test_phase15_floor_is_responsive_for_desktop_and_mobile() -> None:
    css = (_repo_root() / "frontend" / "app" / "globals.css").read_text(
        encoding="utf-8"
    )
    assert "@media (max-width: 780px)" in css
    assert "@media (max-width: 480px)" in css
    assert ".inspectionDrawer" in css
    assert ".universeGrid" in css
    assert ".attentionGrid" in css
