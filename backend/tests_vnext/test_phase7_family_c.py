from __future__ import annotations

import pytest

from aether_vnext.family_c import FamilyCContext, evaluate_family_c_range
from aether_vnext.playbooks import playbook


def test_fx_range_long_requires_close_below_12bar_low_and_ema_not_down() -> None:
    spec = playbook("pb_fx_range_v1_3")
    good = FamilyCContext(
        close=1.0990,
        volatility_percentile=20.0,
        prior_range_high=1.1010,
        prior_range_low=1.1000,
        slope_ema20_current=1.1005,
        slope_ema20_previous=1.1000,
    )
    out = evaluate_family_c_range(
        spec, asset_id="eurusd", side="long", context=good
    )
    assert out.outside_prior_range is True
    assert out.trend_not_confirming is True
    assert out.watch_eligible is True

    down_slope = FamilyCContext(
        close=1.0990,
        volatility_percentile=20.0,
        prior_range_high=1.1010,
        prior_range_low=1.1000,
        slope_ema20_current=1.0995,
        slope_ema20_previous=1.1000,
    )
    assert evaluate_family_c_range(
        spec, asset_id="eurusd", side="long", context=down_slope
    ).watch_eligible is False


def test_fx_range_short_requires_close_above_12bar_high_and_ema_not_up() -> None:
    spec = playbook("pb_fx_range_v1_3")
    good = FamilyCContext(
        close=1.1020,
        volatility_percentile=20.0,
        prior_range_high=1.1010,
        prior_range_low=1.1000,
        slope_ema20_current=1.0995,
        slope_ema20_previous=1.1000,
    )
    assert evaluate_family_c_range(
        spec, asset_id="eurusd", side="short", context=good
    ).watch_eligible is True

    up_slope = FamilyCContext(
        close=1.1020,
        volatility_percentile=20.0,
        prior_range_high=1.1010,
        prior_range_low=1.1000,
        slope_ema20_current=1.1005,
        slope_ema20_previous=1.1000,
    )
    assert evaluate_family_c_range(
        spec, asset_id="eurusd", side="short", context=up_slope
    ).watch_eligible is False


def test_fx_not_down_and_not_up_allow_flat_ema_slope() -> None:
    spec = playbook("pb_fx_range_v1_3")
    long_flat = FamilyCContext(
        close=1.0990,
        volatility_percentile=20.0,
        prior_range_high=1.1010,
        prior_range_low=1.1000,
        slope_ema20_current=1.1000,
        slope_ema20_previous=1.1000,
    )
    short_flat = FamilyCContext(
        close=1.1020,
        volatility_percentile=20.0,
        prior_range_high=1.1010,
        prior_range_low=1.1000,
        slope_ema20_current=1.1000,
        slope_ema20_previous=1.1000,
    )
    assert evaluate_family_c_range(
        spec, asset_id="eurusd", side="long", context=long_flat
    ).watch_eligible is True
    assert evaluate_family_c_range(
        spec, asset_id="eurusd", side="short", context=short_flat
    ).watch_eligible is True


def test_equity_range_uses_explicit_pit_nonconfirmation_without_inventing_formula() -> None:
    spec = playbook("pb_eq_range_v1_3")
    good = FamilyCContext(
        close=99.0,
        volatility_percentile=20.0,
        prior_range_high=101.0,
        prior_range_low=100.0,
        trend_not_confirming=True,
    )
    assert evaluate_family_c_range(
        spec, asset_id="nvda", side="long", context=good
    ).watch_eligible is True

    confirming = FamilyCContext(
        close=99.0,
        volatility_percentile=20.0,
        prior_range_high=101.0,
        prior_range_low=100.0,
        trend_not_confirming=False,
    )
    assert evaluate_family_c_range(
        spec, asset_id="nvda", side="long", context=confirming
    ).watch_eligible is False


def test_family_c_is_forbidden_at_40th_percentile_and_above() -> None:
    spec = playbook("pb_eq_range_v1_3")
    for percentile in (40.0, 50.0, 85.0, 90.0):
        ctx = FamilyCContext(
            close=99.0,
            volatility_percentile=percentile,
            prior_range_high=101.0,
            prior_range_low=100.0,
            trend_not_confirming=True,
        )
        out = evaluate_family_c_range(
            spec, asset_id="nvda", side="long", context=ctx
        )
        assert out.regime_eligible is False
        assert out.watch_eligible is False


def test_range_break_comparison_is_strictly_outside_prior_range() -> None:
    spec = playbook("pb_eq_range_v1_3")
    at_low = FamilyCContext(
        close=100.0,
        volatility_percentile=20.0,
        prior_range_high=101.0,
        prior_range_low=100.0,
        trend_not_confirming=True,
    )
    at_high = FamilyCContext(
        close=101.0,
        volatility_percentile=20.0,
        prior_range_high=101.0,
        prior_range_low=100.0,
        trend_not_confirming=True,
    )
    assert evaluate_family_c_range(
        spec, asset_id="nvda", side="long", context=at_low
    ).outside_prior_range is False
    assert evaluate_family_c_range(
        spec, asset_id="nvda", side="short", context=at_high
    ).outside_prior_range is False


def test_family_c_out_list_is_enforced_by_registry_contract() -> None:
    fx = playbook("pb_fx_range_v1_3")
    eq = playbook("pb_eq_range_v1_3")
    assert fx.allowed_assets == ("eurusd",)
    assert eq.allowed_assets == ("nvda",)

    with pytest.raises(ValueError, match="asset"):
        evaluate_family_c_range(
            fx,
            asset_id="usdjpy",
            side="long",
            context=FamilyCContext(
                close=1.0,
                volatility_percentile=20.0,
                prior_range_high=1.2,
                prior_range_low=1.1,
                slope_ema20_current=1.1,
                slope_ema20_previous=1.1,
            ),
        )


def test_family_c_evaluator_rejects_family_b_definition() -> None:
    with pytest.raises(ValueError, match="Family-C"):
        evaluate_family_c_range(
            playbook("pb_fx_failed_session_v1_3"),
            asset_id="eurusd",
            side="long",
            context=FamilyCContext(
                close=1.0,
                volatility_percentile=20.0,
                prior_range_high=1.2,
                prior_range_low=1.1,
                slope_ema20_current=1.1,
                slope_ema20_previous=1.1,
            ),
        )
