from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from aether_vnext.evidence import SampleDomain
from aether_vnext.profitability import (
    EconomicPath,
    EconomicTrade,
    assert_same_economic_path,
    benchmark_result_payload,
    compare_to_benchmark,
    cost_stress_profile,
    route_metrics,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 22, 30, tzinfo=UTC)


def _path(**overrides) -> EconomicPath:
    values = dict(
        dataset_snapshot_id="dataset-1",
        data_version="bars-v1",
        fill_model_version="fill-v1",
        fee_schedule_version="fees-v1",
        configuration_hash="cfg-9d",
        playbook_version="1.2",
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=T0,
        last_timestamp_utc=T0 + timedelta(days=7),
    )
    values.update(overrides)
    return EconomicPath(**values)


def _trades() -> tuple[EconomicTrade, ...]:
    return (
        EconomicTrade(
            trade_id="t1",
            gross_pnl_usd=20.0,
            base_cost_usd=4.0,
            duration_s=60.0,
            stopped=False,
            capture_efficiency=0.50,
        ),
        EconomicTrade(
            trade_id="t2",
            gross_pnl_usd=-10.0,
            base_cost_usd=2.0,
            duration_s=120.0,
            stopped=True,
            capture_efficiency=0.25,
        ),
    )


@pytest.mark.parametrize("trade_id", (" trade-1 ", 1, ""))
def test_economic_trade_requires_canonical_identity(
    trade_id: object,
) -> None:
    with pytest.raises(ValueError, match="trade_id must be canonical text"):
        EconomicTrade(
            trade_id=trade_id,
            gross_pnl_usd=1.0,
            base_cost_usd=0.0,
            duration_s=1.0,
        )


def test_base_plus25_plus50_cost_stress_uses_same_gross_outcomes() -> None:
    profile = cost_stress_profile(_trades())

    assert profile.base.total_gross_pnl_usd == pytest.approx(10.0)
    assert profile.plus25.total_gross_pnl_usd == pytest.approx(10.0)
    assert profile.plus50.total_gross_pnl_usd == pytest.approx(10.0)

    assert profile.base.total_cost_usd == pytest.approx(6.0)
    assert profile.plus25.total_cost_usd == pytest.approx(7.5)
    assert profile.plus50.total_cost_usd == pytest.approx(9.0)

    assert profile.base.total_net_pnl_usd == pytest.approx(4.0)
    assert profile.plus25.total_net_pnl_usd == pytest.approx(2.5)
    assert profile.plus50.total_net_pnl_usd == pytest.approx(1.0)

    assert profile.base.net_expectancy_usd == pytest.approx(2.0)
    assert profile.plus25.net_expectancy_usd == pytest.approx(1.25)
    assert profile.plus50.net_expectancy_usd == pytest.approx(0.5)


def test_route_metrics_include_pf_win_loss_stop_drawdown_duration_and_capture() -> None:
    metrics = route_metrics(_trades(), cost_multiplier=1.0)
    assert metrics.n == 2
    assert metrics.profit_factor == pytest.approx(16.0 / 12.0)
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.avg_win_usd == pytest.approx(16.0)
    assert metrics.avg_loss_usd == pytest.approx(-12.0)
    assert metrics.stop_rate == pytest.approx(0.5)
    assert metrics.max_drawdown_usd == pytest.approx(12.0)
    assert metrics.median_duration_s == pytest.approx(90.0)
    assert metrics.capture_efficiency == pytest.approx(0.375)


def test_all_winner_sample_has_infinite_profit_factor_without_fake_loss() -> None:
    metrics = route_metrics(
        (
            EconomicTrade(
                trade_id="winner",
                gross_pnl_usd=10.0,
                base_cost_usd=1.0,
                duration_s=60.0,
            ),
        ),
        cost_multiplier=1.0,
    )
    assert math.isinf(metrics.profit_factor)


def test_zero_trade_baseline_is_valid_for_always_flat() -> None:
    metrics = route_metrics((), cost_multiplier=1.0)
    assert metrics.n == 0
    assert metrics.net_expectancy_usd == 0.0
    assert metrics.total_net_pnl_usd == 0.0
    assert metrics.profit_factor == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("dataset_snapshot_id", " dataset-1 "),
        ("data_version", 1),
        ("fill_model_version", ""),
        ("fee_schedule_version", " fees-v1 "),
        ("configuration_hash", 1),
        ("playbook_version", " 1.2 "),
    ),
)
def test_economic_path_requires_canonical_identity(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match=f"{field} must be canonical text"):
        _path(**{field: value})


@pytest.mark.parametrize(
    "field,mutated",
    (
        ("dataset_snapshot_id", "dataset-2"),
        ("data_version", "bars-v2"),
        ("fill_model_version", "fill-v2"),
        ("fee_schedule_version", "fees-v2"),
        ("configuration_hash", "cfg-other"),
        ("playbook_version", "9.9"),
        ("sample_domain", SampleDomain.PAPER_FORWARD),
        ("first_timestamp_utc", T0 + timedelta(seconds=1)),
        ("last_timestamp_utc", T0 + timedelta(days=8)),
    ),
)
def test_candidate_and_baseline_must_share_exact_economic_path(
    field: str,
    mutated: object,
) -> None:
    baseline = _path(**{field: mutated})
    with pytest.raises(ValueError, match="economic path mismatch"):
        assert_same_economic_path(_path(), baseline)


def test_benchmark_comparison_preserves_metrics_but_does_not_invent_winner_rule() -> None:
    comparison = compare_to_benchmark(
        benchmark_id="always_flat",
        candidate_path=_path(),
        baseline_path=_path(),
        candidate_trades=_trades(),
        baseline_trades=(),
    )
    assert comparison.benchmark_id == "always_flat"
    assert comparison.candidate.plus25.net_expectancy_usd == pytest.approx(1.25)
    assert comparison.baseline.plus25.net_expectancy_usd == 0.0
    assert comparison.comparison_rule_bound is False
    assert comparison.not_worse_than_baseline is None
    assert "does not bind" in str(comparison.unresolved_reason)

    payload = benchmark_result_payload(comparison)
    assert payload["benchmark_id"] == "always_flat"
    assert payload["comparison_rule_bound"] is False
    assert payload["not_worse_than_baseline"] is None
    assert payload["candidate"]["plus25"]["net_expectancy_usd"] == pytest.approx(1.25)
    assert payload["baseline"]["plus25"]["net_expectancy_usd"] == 0.0


def test_cost_sensitivity_payload_matches_profitability_evidence_shape() -> None:
    sensitivity = cost_stress_profile(
        _trades()
    ).as_evidence_cost_sensitivity()
    assert sensitivity.base["net_expectancy_usd"] == pytest.approx(2.0)
    assert sensitivity.plus25["net_expectancy_usd"] == pytest.approx(1.25)
    assert sensitivity.plus50["net_expectancy_usd"] == pytest.approx(0.5)


def test_duplicate_trade_identity_fails_closed() -> None:
    duplicate = EconomicTrade(
        trade_id="same",
        gross_pnl_usd=1.0,
        base_cost_usd=0.0,
        duration_s=1.0,
    )
    with pytest.raises(ValueError, match="duplicate trade_id"):
        route_metrics(
            (duplicate, duplicate),
            cost_multiplier=1.0,
        )


def test_cost_multiplier_cannot_be_negative_or_nonfinite() -> None:
    for value in (-1.0, math.inf, math.nan):
        with pytest.raises(ValueError, match="cost_multiplier"):
            route_metrics(_trades(), cost_multiplier=value)

@pytest.mark.parametrize("benchmark_id", (" always_flat ", 1, ""))
def test_benchmark_comparison_requires_canonical_identity(
    benchmark_id: object,
) -> None:
    with pytest.raises(ValueError, match="benchmark_id must be canonical text"):
        compare_to_benchmark(
            benchmark_id=benchmark_id,
            candidate_path=_path(),
            baseline_path=_path(),
            candidate_trades=_trades(),
            baseline_trades=(),
        )

