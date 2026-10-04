from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.evidence import CostSensitivity, ProfitabilityEvidence
from aether_vnext.operator_profitability import (
    ExecutionPanelInput,
    FirmStripInput,
    build_profitability_dashboard,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 26, 23, 45, tzinfo=UTC)


def _evidence(route_id: str = "eurusd:intraday:long") -> ProfitabilityEvidence:
    return ProfitabilityEvidence(
        evidence_id=f"evidence:{route_id}",
        route_id=route_id,
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="policy-p10",
        configuration_hash="cfg-p10",
        data_version="bars-v1",
        fill_model_version="fill-v1",
        fee_schedule_version="fees-v1",
        in_sample_window=None,
        oos_windows=(
            {"fold": 1, "expectancy": 2.0},
            {"fold": 2, "expectancy": 1.0},
            {"fold": 3, "expectancy": 1.5},
        ),
        n_trades=30,
        net_expectancy_usd=2.5,
        profit_factor=1.4,
        win_rate=0.55,
        avg_win_usd=12.0,
        avg_loss_usd=-8.0,
        stop_rate=0.4,
        max_drawdown_usd=40.0,
        max_drawdown_pct=0.02,
        median_duration_s=1800.0,
        capture_efficiency=0.45,
        cost_sensitivity=CostSensitivity(
            base={"net_expectancy_usd": 2.5},
            plus25={"net_expectancy_usd": 1.8},
            plus50={"net_expectancy_usd": 1.0},
        ),
        regime_matrix={"trend": {"n": 20}, "range": {"n": 10}},
        benchmark_result={"benchmark_id": "always_flat"},
        capacity_result={"trusted_keep_ready": True},
        portfolio_contribution={"marginal_drawdown_usd": 5.0},
        model_risks=("unknown_swap_tail",),
        verdict="KEEP_PROBATION",
        reviewer="Review",
        as_of_utc=NOW,
    )


def test_p10_projection_contains_all_source_required_panels() -> None:
    dashboard = build_profitability_dashboard(
        firm_strip=FirmStripInput(
            net_paper_pnl_usd=125.0,
            rolling_expectancy_usd=2.2,
            max_drawdown_usd=55.0,
            portfolio_stop_risk_usd=180.0,
            broker_sleeve_health={
                "kraken_paper": "healthy",
                "tastyfx_paper": "healthy",
            },
            warnings=("carry-model-warning",),
        ),
        evidence_records=(_evidence(),),
        decay_state_by_route={
            "eurusd:intraday:long": "HEALTHY_KEEP",
        },
        review_state_by_route={
            "eurusd:intraday:long": "KEEP_PROBATION",
        },
        traffic_funnel={
            "stage_counts": {
                "UNIVERSE": 100,
                "WATCH": 20,
                "FIRE": 10,
                "SIZE": 8,
                "READY": 6,
                "ORDER": 5,
                "OPEN": 4,
            },
            "first_killer_distribution": {"Scout:no_setup": 80},
            "target_trade_count": None,
        },
        execution_panel=ExecutionPanelInput(
            expected_fill_cost_usd=10.0,
            realized_fill_cost_usd=11.0,
            average_spread_bps=2.0,
            average_slippage_bps=1.0,
            reject_rate=0.05,
            stale_observation_count=2,
            invalid_observation_count=1,
        ),
        additional_model_risks=("missing_depth",),
    )

    assert set(dashboard) == {
        "authority",
        "firm_strip",
        "route_board",
        "traffic_funnel",
        "execution_panel",
        "review_panel",
        "model_risk_panel",
    }
    row = dashboard["route_board"][0]
    assert row["n"] == 30
    assert row["verdict"] == "KEEP_PROBATION"
    assert row["net_expectancy_usd"] == pytest.approx(2.5)
    assert row["profit_factor"] == pytest.approx(1.4)
    assert row["recent_decay_state"] == "HEALTHY_KEEP"
    assert row["configuration_hash"] == "cfg-p10"
    assert row["cost_shock_status"]["plus25"]["positive"] is True

    review = dashboard["review_panel"][0]
    assert review["capacity_result"]["trusted_keep_ready"] is True
    assert review["benchmark_result"]["benchmark_id"] == "always_flat"
    assert review["current_review_state"] == "KEEP_PROBATION"

    assert dashboard["traffic_funnel"]["target_trade_count"] is None
    assert dashboard["model_risk_panel"]["known_omissions"] == [
        "missing_depth",
        "unknown_swap_tail",
    ]


def test_display_law_is_explicitly_read_only_and_non_authoritative() -> None:
    dashboard = build_profitability_dashboard(
        firm_strip=FirmStripInput(
            net_paper_pnl_usd=0.0,
            rolling_expectancy_usd=None,
            max_drawdown_usd=0.0,
            portfolio_stop_risk_usd=0.0,
            broker_sleeve_health={},
            warnings=(),
        ),
        evidence_records=(),
        decay_state_by_route={},
        review_state_by_route={},
        traffic_funnel={"stage_counts": {}, "target_trade_count": None},
        execution_panel=ExecutionPanelInput(
            expected_fill_cost_usd=None,
            realized_fill_cost_usd=None,
            average_spread_bps=None,
            average_slippage_bps=None,
            reject_rate=None,
            stale_observation_count=0,
            invalid_observation_count=0,
        ),
    )
    authority = dashboard["authority"]
    assert authority == {
        "read_only": True,
        "execution_permission": False,
        "may_mutate_route_state": False,
        "may_mutate_risk": False,
        "may_reset_governor": False,
        "display_law": (
            "profitability evidence is observational; seats and typed "
            "state remain authoritative"
        ),
    }


def test_dashboard_rejects_multiple_current_evidence_records_for_same_route() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="one current"):
        build_profitability_dashboard(
            firm_strip=FirmStripInput(
                net_paper_pnl_usd=0.0,
                rolling_expectancy_usd=0.0,
                max_drawdown_usd=0.0,
                portfolio_stop_risk_usd=0.0,
                broker_sleeve_health={},
                warnings=(),
            ),
            evidence_records=(evidence, evidence),
            decay_state_by_route={},
            review_state_by_route={},
            traffic_funnel={},
            execution_panel=ExecutionPanelInput(
                expected_fill_cost_usd=None,
                realized_fill_cost_usd=None,
                average_spread_bps=None,
                average_slippage_bps=None,
                reject_rate=None,
                stale_observation_count=0,
                invalid_observation_count=0,
            ),
        )


def test_execution_panel_validates_reject_rate() -> None:
    with pytest.raises(ValueError, match="reject_rate"):
        ExecutionPanelInput(
            expected_fill_cost_usd=0.0,
            realized_fill_cost_usd=0.0,
            average_spread_bps=0.0,
            average_slippage_bps=0.0,
            reject_rate=1.1,
            stale_observation_count=0,
            invalid_observation_count=0,
        )
