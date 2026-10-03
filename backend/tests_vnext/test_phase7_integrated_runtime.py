from __future__ import annotations

from aether_vnext.family_a import FamilyAContext, evaluate_family_a_structure
from aether_vnext.family_b import FamilyBContext, evaluate_family_b_failure
from aether_vnext.family_c import FamilyCContext, evaluate_family_c_range
from aether_vnext.playbook_engine import resolve_closed_bar_runtime
from aether_vnext.playbooks import PlaybookFamily, playbook


def _a_fx(*, structure: bool):
    return evaluate_family_a_structure(
        playbook("pb_fx_intraday_v1_2"),
        asset_id="eurusd",
        side="long",
        context=FamilyAContext(
            close=1.1010 if structure else 1.0990,
            volatility_percentile=50.0,
            reference_high=1.1000,
            reference_low=1.0980,
            slope_ema20_current=1.1005,
            slope_ema20_previous=1.1000,
        ),
    )


def _b_fx(*, structure: bool):
    return evaluate_family_b_failure(
        playbook("pb_fx_failed_session_v1_3"),
        asset_id="eurusd",
        side="long",
        context=FamilyBContext(
            break_printed=structure,
            bars_since_break=1,
            close_back_inside=structure,
            counter_trend_condition=structure,
            volatility_percentile=50.0,
        ),
    )


def _c_fx(*, structure: bool):
    return evaluate_family_c_range(
        playbook("pb_fx_range_v1_3"),
        asset_id="eurusd",
        side="long",
        context=FamilyCContext(
            close=1.0990 if structure else 1.1005,
            volatility_percentile=20.0,
            prior_range_high=1.1010,
            prior_range_low=1.1000,
            slope_ema20_current=1.1000,
            slope_ema20_previous=1.1000,
        ),
    )


def test_family_a_structure_silences_b_and_c_even_when_they_are_supplied() -> None:
    out = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_a=(_a_fx(structure=True),),
        family_b=(_b_fx(structure=True),),
        family_c=(_c_fx(structure=True),),
    )
    assert out.selected_family is PlaybookFamily.A
    assert [row.playbook_id for row in out.watch_candidates] == [
        "pb_fx_intraday_v1_2"
    ]
    assert out.suppressed_by_precedence == (
        "pb_fx_failed_session_v1_3",
        "pb_fx_range_v1_3",
    )


def test_family_b_wins_when_a_structure_is_false_and_silences_c() -> None:
    out = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_a=(_a_fx(structure=False),),
        family_b=(_b_fx(structure=True),),
        family_c=(_c_fx(structure=True),),
    )
    assert out.selected_family is PlaybookFamily.B
    assert [row.playbook_id for row in out.watch_candidates] == [
        "pb_fx_failed_session_v1_3"
    ]
    assert out.suppressed_by_precedence == ("pb_fx_range_v1_3",)


def test_family_c_is_selected_only_after_a_and_b_are_false() -> None:
    out = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_a=(_a_fx(structure=False),),
        family_b=(_b_fx(structure=False),),
        family_c=(_c_fx(structure=True),),
    )
    assert out.selected_family is PlaybookFamily.C
    assert [row.playbook_id for row in out.watch_candidates] == [
        "pb_fx_range_v1_3"
    ]
    assert out.watch_candidates[0].exit_contract_complete is False
    assert "stop anchor" in str(out.watch_candidates[0].exit_contract_gap)


def test_no_structure_produces_no_watch_candidate() -> None:
    out = resolve_closed_bar_runtime(
        asset_id="eurusd",
        horizon="intraday",
        family_a=(_a_fx(structure=False),),
        family_b=(_b_fx(structure=False),),
        family_c=(_c_fx(structure=False),),
    )
    assert out.selected_family is None
    assert out.reason == "structure_fail"
    assert out.watch_candidates == ()
    assert out.suppressed_by_precedence == ()


def test_raw_family_a_structure_still_blocks_lower_families_when_dependency_fails() -> None:
    rider = evaluate_family_a_structure(
        playbook("pb_eth_rider_v1_2"),
        asset_id="eth",
        side="long",
        context=FamilyAContext(
            close=4001.0,
            volatility_percentile=50.0,
            reference_high=4000.0,
            trend_ema20=4100.0,
            trend_ema50=3900.0,
            btc_parent_watch_or_open_long=False,
            btc_parent_market_regime_eligible=True,
        ),
    )
    failed_break = evaluate_family_b_failure(
        playbook("pb_eth_failed_break_v1_3"),
        asset_id="eth",
        side="short",
        context=FamilyBContext(
            break_printed=True,
            bars_since_break=1,
            close_back_inside=True,
            counter_trend_condition=True,
            volatility_percentile=50.0,
        ),
    )
    out = resolve_closed_bar_runtime(
        asset_id="eth",
        horizon="daily_swing",
        family_a=(rider,),
        family_b=(failed_break,),
    )
    assert rider.structure_rule is True
    assert rider.watch_eligible is False
    assert out.selected_family is PlaybookFamily.A
    assert out.watch_candidates == ()
    assert out.suppressed_by_precedence == (
        "pb_eth_failed_break_v1_3",
    )


def test_multiple_family_a_candidates_can_coexist_before_later_one_open_rule() -> None:
    independent = evaluate_family_a_structure(
        playbook("pb_crypto_swing_v1_2"),
        asset_id="eth",
        side="long",
        context=FamilyAContext(
            close=4001.0,
            volatility_percentile=50.0,
            reference_high=4000.0,
            trend_ema20=4100.0,
            trend_ema50=3900.0,
            btc_daily_close=101000.0,
            btc_daily_ema50=100000.0,
        ),
    )
    rider = evaluate_family_a_structure(
        playbook("pb_eth_rider_v1_2"),
        asset_id="eth",
        side="long",
        context=FamilyAContext(
            close=4001.0,
            volatility_percentile=50.0,
            reference_high=4000.0,
            trend_ema20=4100.0,
            trend_ema50=3900.0,
            btc_parent_watch_or_open_long=True,
            btc_parent_market_regime_eligible=True,
        ),
    )
    out = resolve_closed_bar_runtime(
        asset_id="eth",
        horizon="daily_swing",
        family_a=(rider, independent),
    )
    assert [row.playbook_id for row in out.watch_candidates] == [
        "pb_crypto_swing_v1_2",
        "pb_eth_rider_v1_2",
    ]
    assert out.watch_candidates[0].exit_contract_complete is True
    assert out.watch_candidates[1].exit_contract_complete is False


def test_integrated_runtime_rejects_wrong_asset_or_horizon() -> None:
    row = _a_fx(structure=True)
    try:
        resolve_closed_bar_runtime(
            asset_id="usdjpy",
            horizon="intraday",
            family_a=(row,),
        )
    except ValueError as exc:
        assert "asset mismatch" in str(exc)
    else:
        raise AssertionError("asset mismatch was not rejected")

    try:
        resolve_closed_bar_runtime(
            asset_id="eurusd",
            horizon="swing",
            family_a=(row,),
        )
    except ValueError as exc:
        assert "horizon mismatch" in str(exc)
    else:
        raise AssertionError("horizon mismatch was not rejected")
