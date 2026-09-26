from __future__ import annotations

import pytest

from aether_vnext.family_a import FamilyAContext, evaluate_family_a_structure
from aether_vnext.playbooks import playbook


def test_crypto_breakout_requires_btc_market_regime_trend_break_and_mid_vol() -> None:
    spec = playbook("pb_crypto_swing_v1_2")
    good = FamilyAContext(
        close=101.0,
        volatility_percentile=50.0,
        reference_high=100.0,
        trend_ema20=110.0,
        trend_ema50=100.0,
        btc_daily_close=105.0,
        btc_daily_ema50=100.0,
    )
    out = evaluate_family_a_structure(
        spec, asset_id="btc", side="long", context=good
    )
    assert out.structure_rule is True
    assert out.watch_eligible is True

    bad_market = FamilyAContext(
        close=101.0,
        volatility_percentile=50.0,
        reference_high=100.0,
        trend_ema20=110.0,
        trend_ema50=100.0,
        btc_daily_close=99.0,
        btc_daily_ema50=100.0,
    )
    assert evaluate_family_a_structure(
        spec, asset_id="btc", side="long", context=bad_market
    ).structure_rule is False

    low_vol = FamilyAContext(
        close=101.0,
        volatility_percentile=39.9,
        reference_high=100.0,
        trend_ema20=110.0,
        trend_ema50=100.0,
        btc_daily_close=105.0,
        btc_daily_ema50=100.0,
    )
    assert evaluate_family_a_structure(
        spec, asset_id="btc", side="long", context=low_vol
    ).structure_rule is False


def test_eth_independent_crypto_route_still_requires_btc_market_regime() -> None:
    spec = playbook("pb_crypto_swing_v1_2")
    ctx = FamilyAContext(
        close=4001.0,
        volatility_percentile=50.0,
        reference_high=4000.0,
        trend_ema20=4100.0,
        trend_ema50=3900.0,
        btc_daily_close=101_000.0,
        btc_daily_ema50=100_000.0,
    )
    out = evaluate_family_a_structure(
        spec, asset_id="eth", side="long", context=ctx
    )
    assert out.watch_eligible is True


def test_eth_rider_keeps_structure_and_dependency_as_separate_gates() -> None:
    spec = playbook("pb_eth_rider_v1_2")
    blocked = FamilyAContext(
        close=4001.0,
        volatility_percentile=50.0,
        reference_high=4000.0,
        trend_ema20=4100.0,
        trend_ema50=3900.0,
        btc_parent_watch_or_open_long=False,
        btc_parent_market_regime_eligible=True,
    )
    out = evaluate_family_a_structure(
        spec, asset_id="eth", side="long", context=blocked
    )
    assert out.structure_rule is True
    assert out.dependency_ok is False
    assert out.watch_eligible is False

    allowed = FamilyAContext(
        close=4001.0,
        volatility_percentile=50.0,
        reference_high=4000.0,
        trend_ema20=4100.0,
        trend_ema50=3900.0,
        btc_parent_watch_or_open_long=True,
        btc_parent_market_regime_eligible=True,
    )
    assert evaluate_family_a_structure(
        spec, asset_id="eth", side="long", context=allowed
    ).watch_eligible is True


@pytest.mark.parametrize(
    ("side", "close", "current", "previous", "expected"),
    (
        ("long", 1.1010, 1.1005, 1.1000, True),
        ("long", 1.1010, 1.0995, 1.1000, False),
        ("short", 1.0990, 1.0995, 1.1000, True),
        ("short", 1.0990, 1.1005, 1.1000, False),
    ),
)
def test_fx_intraday_uses_ema20_slope_against_session_extreme(
    side: str,
    close: float,
    current: float,
    previous: float,
    expected: bool,
) -> None:
    spec = playbook("pb_fx_intraday_v1_2")
    ctx = FamilyAContext(
        close=close,
        volatility_percentile=50.0,
        reference_high=1.1000,
        reference_low=1.1000,
        slope_ema20_current=current,
        slope_ema20_previous=previous,
    )
    out = evaluate_family_a_structure(
        spec, asset_id="eurusd", side=side, context=ctx
    )
    assert out.structure_rule is expected


@pytest.mark.parametrize(
    "playbook_id,asset_id,horizon",
    (
        ("pb_fx_swing_v1_2", "eurusd", "swing"),
        ("pb_idx_intraday_v1_2", "mes", "intraday"),
        ("pb_idx_swing_v1_2", "mnq", "swing"),
        ("pb_metal_intraday_v1_2", "mgc", "intraday"),
        ("pb_metal_swing_v1_2", "mgc", "swing"),
        ("pb_energy_intraday_v1_2", "mcl", "intraday"),
        ("pb_energy_swing_v1_2", "mcl", "swing"),
        ("pb_rates_swing_v1_2", "us10y", "swing"),
        ("pb_eq_scalp_v1_2", "nvda", "scalp"),
        ("pb_eq_intraday_v1_2", "tsla", "intraday"),
        ("pb_eq_swing_v1_2", "pltr", "swing"),
    ),
)
def test_level_trend_family_a_routes_require_break_and_same_side_ema_alignment(
    playbook_id: str,
    asset_id: str,
    horizon: str,
) -> None:
    spec = playbook(playbook_id)
    assert spec.horizon == horizon

    long_ctx = FamilyAContext(
        close=101.0,
        volatility_percentile=50.0,
        reference_high=100.0,
        trend_ema20=110.0,
        trend_ema50=100.0,
    )
    assert evaluate_family_a_structure(
        spec, asset_id=asset_id, side="long", context=long_ctx
    ).watch_eligible is True

    short_ctx = FamilyAContext(
        close=99.0,
        volatility_percentile=50.0,
        reference_low=100.0,
        trend_ema20=90.0,
        trend_ema50=100.0,
    )
    assert evaluate_family_a_structure(
        spec, asset_id=asset_id, side="short", context=short_ctx
    ).watch_eligible is True


def test_breakout_and_trend_comparisons_are_strict() -> None:
    spec = playbook("pb_eq_intraday_v1_2")
    at_level = FamilyAContext(
        close=100.0,
        volatility_percentile=50.0,
        reference_high=100.0,
        trend_ema20=101.0,
        trend_ema50=100.0,
    )
    assert evaluate_family_a_structure(
        spec, asset_id="nvda", side="long", context=at_level
    ).structure_rule is False

    equal_ema = FamilyAContext(
        close=101.0,
        volatility_percentile=50.0,
        reference_high=100.0,
        trend_ema20=100.0,
        trend_ema50=100.0,
    )
    assert evaluate_family_a_structure(
        spec, asset_id="nvda", side="long", context=equal_ema
    ).structure_rule is False


def test_benched_fx_scalp_remains_registered_but_is_not_evaluated() -> None:
    spec = playbook("pb_fx_scalp_v1_2")
    out = evaluate_family_a_structure(
        spec,
        asset_id="eurusd",
        side="long",
        context=FamilyAContext(
            close=1.10,
            volatility_percentile=50.0,
        ),
    )
    assert out.definition_enabled is False
    assert out.structure_rule is False
    assert out.watch_eligible is False


def test_family_a_evaluator_rejects_family_b_definition() -> None:
    with pytest.raises(ValueError, match="Family-A"):
        evaluate_family_a_structure(
            playbook("pb_fx_failed_session_v1_3"),
            asset_id="eurusd",
            side="long",
            context=FamilyAContext(
                close=1.10,
                volatility_percentile=50.0,
            ),
        )
