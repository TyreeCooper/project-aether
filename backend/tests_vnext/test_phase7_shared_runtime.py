from __future__ import annotations

from datetime import timedelta

import pytest

from aether_vnext.playbook_runtime import (
    EvaluationDisposition,
    VolatilityBand,
    clock_spec_for_playbook,
    family_regime_eligible,
    playbook_evaluation_key,
    resolve_family_precedence,
    volatility_band,
)
from aether_vnext.playbooks import PlaybookFamily, playbook


def test_sample_accounting_dispositions_are_exact_and_complete() -> None:
    assert [row.value for row in EvaluationDisposition] == [
        "not_due",
        "regime_block",
        "structure_fail",
        "dependency_block",
        "cost_edge_fail",
        "risk_block",
        "venue_block",
        "ticket_created",
        "trade_opened",
        "trade_closed",
    ]


@pytest.mark.parametrize(
    ("percentile", "expected"),
    (
        (0.0, VolatilityBand.BELOW_40),
        (39.999, VolatilityBand.BELOW_40),
        (40.0, VolatilityBand.ELIGIBLE_40_85),
        (85.0, VolatilityBand.ELIGIBLE_40_85),
        (85.001, VolatilityBand.ABOVE_85),
        (100.0, VolatilityBand.ABOVE_85),
    ),
)
def test_volatility_band_boundaries_are_source_exact(
    percentile: float,
    expected: VolatilityBand,
) -> None:
    assert volatility_band(percentile) is expected


@pytest.mark.parametrize("bad", (-0.001, 100.001))
def test_volatility_percentile_outside_closed_range_is_rejected(
    bad: float,
) -> None:
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        volatility_band(bad)


def test_family_a_and_b_use_mid_vol_while_c_uses_low_vol() -> None:
    for family in (PlaybookFamily.A, PlaybookFamily.B):
        assert family_regime_eligible(
            family, volatility_percentile=40.0
        ) is True
        assert family_regime_eligible(
            family, volatility_percentile=85.0
        ) is True
        assert family_regime_eligible(
            family, volatility_percentile=39.9
        ) is False
        assert family_regime_eligible(
            family, volatility_percentile=85.1
        ) is False

    assert family_regime_eligible(
        PlaybookFamily.C, volatility_percentile=39.9
    ) is True
    assert family_regime_eligible(
        PlaybookFamily.C, volatility_percentile=40.0
    ) is False
    assert family_regime_eligible(
        PlaybookFamily.C, volatility_percentile=85.0
    ) is False


def test_same_bar_precedence_is_strict_a_then_b_then_c() -> None:
    all_true = resolve_family_precedence(
        family_a_structure_rule=True,
        family_b_fail_event=True,
        family_c_structure_rule=True,
    )
    assert all_true.selected_family is PlaybookFamily.A

    b_over_c = resolve_family_precedence(
        family_a_structure_rule=False,
        family_b_fail_event=True,
        family_c_structure_rule=True,
    )
    assert b_over_c.selected_family is PlaybookFamily.B

    c_only = resolve_family_precedence(
        family_a_structure_rule=False,
        family_b_fail_event=False,
        family_c_structure_rule=True,
    )
    assert c_only.selected_family is PlaybookFamily.C

    none = resolve_family_precedence(
        family_a_structure_rule=False,
        family_b_fail_event=False,
        family_c_structure_rule=False,
    )
    assert none.selected_family is None
    assert none.reason == "structure_fail"


def test_clock_binding_uses_explicit_playbook_interval_not_horizon() -> None:
    fx_scalp = clock_spec_for_playbook(
        playbook("pb_fx_scalp_v1_2"),
        asset_id="eurusd",
        side="long",
    )
    idx_scalp = clock_spec_for_playbook(
        playbook("pb_idx_scalp_v1_2"),
        asset_id="mes",
        side="long",
    )
    eq_swing = clock_spec_for_playbook(
        playbook("pb_eq_swing_v1_2"),
        asset_id="nvda",
        side="long",
    )

    assert fx_scalp.horizon == "scalp"
    assert fx_scalp.trigger_interval == timedelta(minutes=1)
    assert fx_scalp.active is False

    assert idx_scalp.horizon == "scalp"
    assert idx_scalp.trigger_interval == timedelta(minutes=15)
    assert idx_scalp.active is True

    assert eq_swing.horizon == "swing"
    assert eq_swing.trigger_interval == timedelta(minutes=15)


def test_operationally_disabled_crypto_short_clock_is_inactive() -> None:
    spec = clock_spec_for_playbook(
        playbook("pb_crypto_failed_break_v1_3"),
        asset_id="btc",
        side="short",
    )
    assert spec.active is False
    assert spec.trigger_interval == timedelta(hours=1)


def test_evaluation_key_includes_playbook_identity() -> None:
    independent = playbook_evaluation_key(
        playbook("pb_crypto_swing_v1_2"),
        asset_id="eth",
        side="long",
    )
    rider = playbook_evaluation_key(
        playbook("pb_eth_rider_v1_2"),
        asset_id="eth",
        side="long",
    )
    assert independent != rider
    assert independent.endswith("|eth|long|daily_swing")
    assert rider.endswith("|eth|long|daily_swing")


def test_evaluation_key_rejects_asset_or_side_outside_playbook_contract() -> None:
    spec = playbook("pb_fx_range_v1_3")
    with pytest.raises(ValueError, match="asset"):
        playbook_evaluation_key(spec, asset_id="usdjpy", side="long")
    with pytest.raises(ValueError, match="side"):
        playbook_evaluation_key(spec, asset_id="eurusd", side="flat")
