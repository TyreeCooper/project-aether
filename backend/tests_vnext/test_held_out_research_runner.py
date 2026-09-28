from __future__ import annotations

from aether_vnext.held_out_research_runner import (
    REQUIRED_INDICATORS,
    canonical_held_out_research_plan,
    preflight_canonical_held_out_research_runner,
)


def test_canonical_research_plan_matches_74_route_burnin_universe() -> None:
    rows = canonical_held_out_research_plan()
    assert len(rows) == 74
    assert len(
        {(row.route_id, row.playbook_id) for row in rows}
    ) == 74
    assert all(row.playbook_version for row in rows)
    assert all(row.mechanism_class for row in rows)


def test_research_runner_fails_closed_on_unbound_indicator_math() -> None:
    result = preflight_canonical_held_out_research_runner()

    assert result.startable is False
    assert result.route_count == 74
    assert result.required_indicators == REQUIRED_INDICATORS
    assert result.blockers == (
        "ema_calculation_convention_unbound",
        "atr_calculation_convention_unbound",
        "realized_vol_calculation_convention_unbound",
    )


def test_prior_closed_range_is_not_a_runner_blocker() -> None:
    result = preflight_canonical_held_out_research_runner()
    assert "prior_closed_bar_range" in result.required_indicators
    assert (
        "prior_closed_bar_range_calculation_convention_unbound"
        not in result.blockers
    )
