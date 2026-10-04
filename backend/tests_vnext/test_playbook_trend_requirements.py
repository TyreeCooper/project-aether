from __future__ import annotations

from datetime import timedelta

import pytest

from aether_vnext.playbook_trend_requirements import (
    PLAYBOOK_TREND_REQUIREMENTS,
    TrendRuleKind,
    trend_requirement,
)
from aether_vnext.playbooks import PlaybookFamily, playbook


def test_all_executable_family_a_playbooks_have_source_bound_trend_rules() -> None:
    expected = {
        "pb_crypto_swing_v1_2",
        "pb_eth_rider_v1_2",
        "pb_fx_intraday_v1_2",
        "pb_fx_swing_v1_2",
        "pb_idx_scalp_v1_2",
        "pb_idx_intraday_v1_2",
        "pb_idx_swing_v1_2",
        "pb_metal_intraday_v1_2",
        "pb_metal_swing_v1_2",
        "pb_energy_intraday_v1_2",
        "pb_energy_swing_v1_2",
        "pb_rates_swing_v1_2",
        "pb_eq_scalp_v1_2",
        "pb_eq_intraday_v1_2",
        "pb_eq_swing_v1_2",
    }

    assert set(PLAYBOOK_TREND_REQUIREMENTS) == expected
    assert all(
        playbook(playbook_id).family is PlaybookFamily.A
        for playbook_id in expected
    )
    assert all(
        playbook(playbook_id).scout_definition_enabled
        for playbook_id in expected
    )


def test_fx_intraday_uses_one_hour_ema20_slope() -> None:
    req = trend_requirement("pb_fx_intraday_v1_2")
    assert req.rule_kind is TrendRuleKind.EMA20_SLOPE
    assert req.interval == timedelta(hours=1)
    assert req.interval_label == "1h"


@pytest.mark.parametrize(
    "playbook_id",
    (
        "pb_crypto_swing_v1_2",
        "pb_eth_rider_v1_2",
        "pb_fx_swing_v1_2",
        "pb_rates_swing_v1_2",
    ),
)
def test_daily_level_bias_is_explicit(playbook_id: str) -> None:
    req = trend_requirement(playbook_id)
    assert req.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL
    assert req.interval == timedelta(days=1)
    assert req.interval_label == "1d"


@pytest.mark.parametrize(
    "playbook_id",
    (
        "pb_metal_intraday_v1_2",
        "pb_metal_swing_v1_2",
        "pb_energy_intraday_v1_2",
        "pb_energy_swing_v1_2",
    ),
)
def test_metal_and_energy_use_one_hour_level_bias(playbook_id: str) -> None:
    req = trend_requirement(playbook_id)
    assert req.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL
    assert req.interval == timedelta(hours=1)
    assert req.interval_label == "1h"


@pytest.mark.parametrize(
    "playbook_id",
    (
        "pb_idx_scalp_v1_2",
        "pb_idx_intraday_v1_2",
        "pb_idx_swing_v1_2",
        "pb_eq_scalp_v1_2",
        "pb_eq_intraday_v1_2",
        "pb_eq_swing_v1_2",
    ),
)
def test_index_and_equity_use_fifteen_minute_level_bias(
    playbook_id: str,
) -> None:
    req = trend_requirement(playbook_id)
    assert req.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL
    assert req.interval == timedelta(minutes=15)
    assert req.interval_label == "15m"


def test_same_interval_and_higher_interval_requirements_are_distinguishable() -> None:
    assert (
        trend_requirement("pb_eq_swing_v1_2").interval
        == playbook("pb_eq_swing_v1_2").trigger_interval
    )
    assert (
        trend_requirement("pb_metal_swing_v1_2").interval
        > playbook("pb_metal_swing_v1_2").trigger_interval
    )
    assert (
        trend_requirement("pb_rates_swing_v1_2").interval
        > playbook("pb_rates_swing_v1_2").trigger_interval
    )


def test_benched_fx_scalp_does_not_gain_an_invented_trend_rule() -> None:
    spec = playbook("pb_fx_scalp_v1_2")
    assert spec.scout_definition_enabled is False
    with pytest.raises(ValueError, match="no source-bound executable"):
        trend_requirement(spec.playbook_id)
