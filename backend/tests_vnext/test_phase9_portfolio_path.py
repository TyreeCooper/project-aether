from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.diagnostics import (
    ConcentrationTrade,
    PathTrade,
    PortfolioRouteOutcome,
    concentration_diagnostics,
    path_diagnostics,
    portfolio_diagnostics,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 22, 45, tzinfo=UTC)


def test_path_diagnostics_capture_drawdown_streak_recovery_and_tail_risk() -> None:
    rows = (
        PathTrade("t1", T0, 10.0, 5.0),
        PathTrade("t2", T0 + timedelta(hours=1), -4.0, 4.0),
        PathTrade("t3", T0 + timedelta(hours=2), -6.0, 3.0),
        PathTrade("t4", T0 + timedelta(hours=3), 12.0, 4.0),
    )
    out = path_diagnostics(rows)
    assert out.n == 4
    assert out.max_drawdown_usd == pytest.approx(10.0)
    assert out.longest_losing_streak == 2
    assert out.max_recovery_duration_s == pytest.approx(2 * 3600.0)
    assert out.sample_ends_underwater is False
    assert out.worst_tail_loss_r == pytest.approx(2.0)
    assert out.resampled_path_stress_status == "UNBOUND_POLICY"


def test_unrecovered_drawdown_is_visible_at_sample_end() -> None:
    out = path_diagnostics(
        (
            PathTrade("t1", T0, 5.0, 5.0),
            PathTrade("t2", T0 + timedelta(hours=1), -2.0, 2.0),
            PathTrade("t3", T0 + timedelta(hours=3), -1.0, 1.0),
        )
    )
    assert out.sample_ends_underwater is True
    assert out.max_recovery_duration_s == pytest.approx(2 * 3600.0)


def test_concentration_diagnostics_keep_denominator_behavior_explicit() -> None:
    out = concentration_diagnostics(
        (
            ConcentrationTrade("t1", 10.0, "eurusd", "long", "trend", "f1"),
            ConcentrationTrade("t2", -2.0, "eurusd", "short", "trend", "f1"),
            ConcentrationTrade("t3", 2.0, "usdjpy", "long", "range", "f2"),
        )
    )
    assert out["largest_trade_pct_total_pnl"] == pytest.approx(1.0)
    assert out["top_decile_trade_pct_total_pnl"] == pytest.approx(1.0)
    assert out["best_fold_pct_total_pnl"] == pytest.approx(0.8)
    assert out["asset_concentration"]["measure"] == "max_trade_count_share"
    assert out["asset_concentration"]["value"] == pytest.approx(2 / 3)


def test_portfolio_diagnostics_report_co_loss_stress_marginal_and_fragmentation() -> None:
    rows = (
        PortfolioRouteOutcome(
            "e1", T0, "route-a", -5.0, 100.0, 3.0, True,
            same_bet_group="beta",
        ),
        PortfolioRouteOutcome(
            "e1", T0, "route-b", -4.0, 80.0, 2.0, True,
            same_bet_group="beta",
        ),
        PortfolioRouteOutcome(
            "e2", T0 + timedelta(hours=1), "route-a", 8.0, 100.0, 3.0, False,
        ),
        PortfolioRouteOutcome(
            "e2", T0 + timedelta(hours=1), "route-b", -1.0, 80.0, 2.0, False,
            broker_local_profitable_rejection=True,
        ),
    )
    out = portfolio_diagnostics(rows, firm_equity_usd=10_000.0)
    pair = out["co_loss"]["route-a|route-b"]
    assert pair["both_present_count"] == 2
    assert pair["both_loss_count"] == 1
    assert pair["both_loss_rate"] == pytest.approx(0.5)

    stress = out["simultaneous_loss_stress"]
    assert stress["portfolio_limit_usd"] == pytest.approx(300.0)
    assert stress["max_stop_risk_usd"] == pytest.approx(180.0)
    assert stress["breached"] is False

    frag = out["capital_fragmentation"]
    assert frag["profitable_rejection_count"] == 1
    assert frag["rejected_expected_return_usd"] == pytest.approx(2.0)

    overlap = out["opportunity_overlap"]
    assert overlap["overlap_episode_count"] == 1
    assert overlap["overlap_episode_rate"] == pytest.approx(0.5)
    assert overlap["inference_policy"] == "explicit_group_only"

    assert set(out["marginal_contribution"]) == {"route-a", "route-b"}


def test_simultaneous_stop_stress_can_breach_frozen_portfolio_limit() -> None:
    rows = (
        PortfolioRouteOutcome("e1", T0, "a", -1.0, 200.0, 1.0, True),
        PortfolioRouteOutcome("e1", T0, "b", -1.0, 150.0, 1.0, True),
    )
    out = portfolio_diagnostics(rows, firm_equity_usd=10_000.0)
    assert out["simultaneous_loss_stress"]["breached"] is True
    assert out["simultaneous_loss_stress"]["max_utilization"] == pytest.approx(
        350.0 / 300.0
    )


def test_duplicate_portfolio_episode_route_fails_closed() -> None:
    row = PortfolioRouteOutcome("e1", T0, "a", 1.0, 10.0, 1.0, False)
    with pytest.raises(ValueError, match="duplicate route outcome"):
        portfolio_diagnostics((row, row), firm_equity_usd=10_000.0)
