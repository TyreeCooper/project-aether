from __future__ import annotations

import pytest

from aether_vnext.family_b import (
    FAIL_WINDOWS,
    FamilyBContext,
    evaluate_family_b_failure,
    fail_window_bars,
)
from aether_vnext.playbooks import playbook


EXPECTED_WINDOWS = {
    "pb_crypto_failed_break_v1_3": 12,
    "pb_eth_failed_break_v1_3": 12,
    "pb_fx_failed_session_v1_3": 4,
    "pb_fx_failed_swing_v1_3": 8,
    "pb_idx_failed_v1_3": 3,
    "pb_metal_failed_v1_3": 4,
    "pb_energy_failed_v1_3": 4,
    "pb_rates_failed_v1_3": 8,
    "pb_eq_failed_v1_3": 3,
}


def _good(*, bars: int, **overrides) -> FamilyBContext:
    values = dict(
        break_printed=True,
        bars_since_break=bars,
        close_back_inside=True,
        counter_trend_condition=True,
        volatility_percentile=50.0,
        position_key_open=False,
        locate_ok=True,
    )
    values.update(overrides)
    return FamilyBContext(**values)


def test_all_nine_family_b_fail_windows_are_source_pinned() -> None:
    assert dict(FAIL_WINDOWS) == EXPECTED_WINDOWS
    for playbook_id, expected in EXPECTED_WINDOWS.items():
        assert fail_window_bars(playbook(playbook_id)) == expected


@pytest.mark.parametrize("playbook_id", tuple(EXPECTED_WINDOWS))
def test_each_family_b_definition_accepts_last_closed_bar_inside_its_window(
    playbook_id: str,
) -> None:
    spec = playbook(playbook_id)
    asset_id = spec.allowed_assets[0]
    side = spec.allowed_sides[0]
    out = evaluate_family_b_failure(
        spec,
        asset_id=asset_id,
        side=side,
        context=_good(bars=EXPECTED_WINDOWS[playbook_id]),
    )
    if playbook_id in {
        "pb_crypto_failed_break_v1_3",
        "pb_eth_failed_break_v1_3",
    }:
        assert out.definition_enabled is False
        assert out.watch_eligible is False
    else:
        assert out.structure_rule is True
        assert out.watch_eligible is True


def test_failure_event_must_be_on_a_later_closed_bar_not_break_bar() -> None:
    spec = playbook("pb_fx_failed_session_v1_3")
    on_break_bar = evaluate_family_b_failure(
        spec,
        asset_id="eurusd",
        side="short",
        context=_good(bars=0),
    )
    assert on_break_bar.within_fail_window is False
    assert on_break_bar.watch_eligible is False


def test_failure_event_after_window_is_rejected() -> None:
    spec = playbook("pb_idx_failed_v1_3")
    too_late = evaluate_family_b_failure(
        spec,
        asset_id="mes",
        side="long",
        context=_good(bars=4),
    )
    assert too_late.fail_window_bars == 3
    assert too_late.within_fail_window is False
    assert too_late.watch_eligible is False


@pytest.mark.parametrize(
    "override",
    (
        {"break_printed": False},
        {"close_back_inside": False},
        {"counter_trend_condition": False},
        {"volatility_percentile": 39.9},
        {"volatility_percentile": 85.1},
    ),
)
def test_shared_failed_break_geometry_fails_closed_when_any_gate_is_false(
    override: dict[str, object],
) -> None:
    spec = playbook("pb_metal_failed_v1_3")
    out = evaluate_family_b_failure(
        spec,
        asset_id="mgc",
        side="long",
        context=_good(bars=1, **override),
    )
    assert out.watch_eligible is False


def test_family_b_is_silent_when_same_position_key_is_already_open() -> None:
    spec = playbook("pb_fx_failed_swing_v1_3")
    out = evaluate_family_b_failure(
        spec,
        asset_id="eurusd",
        side="long",
        context=_good(bars=1, position_key_open=True),
    )
    assert out.silent_existing_open is True
    assert out.structure_rule is False
    assert out.watch_eligible is False


def test_equity_failed_break_short_requires_locate() -> None:
    spec = playbook("pb_eq_failed_v1_3")
    missing = evaluate_family_b_failure(
        spec,
        asset_id="nvda",
        side="short",
        context=_good(bars=1, locate_ok=None),
    )
    assert missing.locate_ok is False
    assert missing.watch_eligible is False

    allowed = evaluate_family_b_failure(
        spec,
        asset_id="nvda",
        side="short",
        context=_good(bars=1, locate_ok=True),
    )
    assert allowed.locate_ok is True
    assert allowed.watch_eligible is True


def test_crypto_short_failed_breaks_remain_defined_but_operationally_disabled() -> None:
    for playbook_id, asset_id in (
        ("pb_crypto_failed_break_v1_3", "btc"),
        ("pb_eth_failed_break_v1_3", "eth"),
    ):
        spec = playbook(playbook_id)
        out = evaluate_family_b_failure(
            spec,
            asset_id=asset_id,
            side="short",
            context=_good(bars=1),
        )
        assert out.structure_rule is True
        assert out.definition_enabled is False
        assert out.watch_eligible is False


def test_family_b_evaluator_rejects_family_a_definition() -> None:
    with pytest.raises(ValueError, match="Family-B"):
        evaluate_family_b_failure(
            playbook("pb_fx_intraday_v1_2"),
            asset_id="eurusd",
            side="long",
            context=_good(bars=1),
        )
