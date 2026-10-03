from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.freeze import EvidenceState, US10Y_TICK_POINTS
from aether_vnext.playbook_exits import (
    PLAYBOOK_EXIT_RULES,
    InvalidationRule,
    StopAnchor,
    TargetRule,
    build_exit_geometry,
    exit_rule,
    source_complete_playbook_ids,
    unresolved_playbook_ids,
)
from aether_vnext.playbooks import PLAYBOOK_REGISTRY, playbook


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 20, 30, tzinfo=UTC)


def test_exit_rule_registry_covers_all_26_candidates_and_excludes_bench() -> None:
    candidate_ids = {
        row.playbook_id
        for row in PLAYBOOK_REGISTRY.values()
        if row.evidence_state is EvidenceState.CANDIDATE
    }
    assert set(PLAYBOOK_EXIT_RULES) == candidate_ids
    assert len(PLAYBOOK_EXIT_RULES) == 26
    assert "pb_fx_scalp_v1_2" not in PLAYBOOK_EXIT_RULES


def test_source_gaps_are_explicit_not_silently_filled() -> None:
    assert unresolved_playbook_ids() == (
        "pb_eq_range_v1_3",
        "pb_eth_rider_v1_2",
        "pb_fx_range_v1_3",
    )
    assert len(source_complete_playbook_ids()) == 23


def test_crypto_swing_stop_target_invalidation_and_deadline_are_exact() -> None:
    spec = playbook("pb_crypto_swing_v1_2")
    out = build_exit_geometry(
        spec,
        side="long",
        entry_price=100.0,
        atr=10.0,
        filled_at_utc=T0,
        frozen_breakout_level=95.0,
        prior_range_low=80.0,
    )
    assert out.hard_stop_price == pytest.approx(78.0)
    assert out.structure_invalidation_level == pytest.approx(95.0)
    assert out.first_target_price == pytest.approx(110.0)
    assert out.time_stop_deadline_utc == T0 + timedelta(days=5)
    assert out.source_complete is True


@pytest.mark.parametrize(
    ("side", "expected_stop", "expected_target"),
    (
        ("long", 98.5, 102.0),
        ("short", 101.5, 98.0),
    ),
)
def test_fx_intraday_uses_frozen_breakout_stop_and_entry_plusminus_one_atr_target(
    side: str,
    expected_stop: float,
    expected_target: float,
) -> None:
    out = build_exit_geometry(
        playbook("pb_fx_intraday_v1_2"),
        side=side,
        entry_price=100.0,
        atr=2.0,
        filled_at_utc=T0,
        frozen_breakout_level=101.5 if side == "short" else 101.5,
    )
    # Long: 101.5 - 3.0 = 98.5. Short: 101.5 + 3.0 = 104.5.
    if side == "long":
        assert out.hard_stop_price == pytest.approx(98.5)
    else:
        assert out.hard_stop_price == pytest.approx(104.5)
    assert out.first_target_price == pytest.approx(expected_target)
    assert out.time_stop_deadline_utc == T0 + timedelta(minutes=180)


@pytest.mark.parametrize(
    ("playbook_id", "multiplier", "deadline"),
    (
        ("pb_idx_scalp_v1_2", 1.2, timedelta(minutes=45)),
        ("pb_idx_intraday_v1_2", 1.2, timedelta(minutes=180)),
        ("pb_idx_swing_v1_2", 1.2, timedelta(days=5)),
        ("pb_metal_intraday_v1_2", 1.5, timedelta(minutes=180)),
        ("pb_metal_swing_v1_2", 1.5, timedelta(days=5)),
        ("pb_energy_intraday_v1_2", 1.5, timedelta(minutes=180)),
        ("pb_energy_swing_v1_2", 1.5, timedelta(days=5)),
        ("pb_eq_scalp_v1_2", 1.2, timedelta(minutes=45)),
        ("pb_eq_intraday_v1_2", 1.2, timedelta(minutes=180)),
        ("pb_eq_swing_v1_2", 1.2, timedelta(days=5)),
    ),
)
def test_family_a_entry_anchored_stops_and_time_stops(
    playbook_id: str,
    multiplier: float,
    deadline: timedelta,
) -> None:
    spec = playbook(playbook_id)
    asset = spec.allowed_assets[0]
    del asset
    out = build_exit_geometry(
        spec,
        side="long",
        entry_price=100.0,
        atr=4.0,
        filled_at_utc=T0,
        frozen_breakout_level=99.0,
    )
    assert out.hard_stop_price == pytest.approx(100.0 - multiplier * 4.0)
    assert out.structure_invalidation_level == pytest.approx(99.0)
    assert out.time_stop_deadline_utc == T0 + deadline


def test_zn_family_a_stop_is_rounded_away_from_entry_to_valid_tick() -> None:
    out = build_exit_geometry(
        playbook("pb_rates_swing_v1_2"),
        side="long",
        entry_price=112.0,
        atr=0.031,
        filled_at_utc=T0,
        frozen_breakout_level=111.95,
    )
    ticks = out.hard_stop_price / US10Y_TICK_POINTS
    assert ticks == pytest.approx(round(ticks))
    assert out.hard_stop_price <= 112.0 - 1.5 * 0.031


@pytest.mark.parametrize(
    ("playbook_id", "side", "multiplier", "deadline"),
    (
        ("pb_crypto_failed_break_v1_3", "short", 0.2, timedelta(hours=24)),
        ("pb_eth_failed_break_v1_3", "short", 0.2, timedelta(hours=24)),
        ("pb_fx_failed_session_v1_3", "long", 1.2, timedelta(minutes=180)),
        ("pb_fx_failed_swing_v1_3", "short", 1.2, timedelta(days=5)),
        ("pb_idx_failed_v1_3", "long", 1.2, timedelta(minutes=180)),
        ("pb_metal_failed_v1_3", "short", 1.2, timedelta(minutes=180)),
        ("pb_energy_failed_v1_3", "long", 1.2, timedelta(minutes=180)),
        ("pb_eq_failed_v1_3", "short", 1.2, timedelta(minutes=180)),
    ),
)
def test_family_b_stop_is_beyond_failed_extreme_and_target_is_midpoint(
    playbook_id: str,
    side: str,
    multiplier: float,
    deadline: timedelta,
) -> None:
    out = build_exit_geometry(
        playbook(playbook_id),
        side=side,
        entry_price=100.0,
        atr=5.0,
        filled_at_utc=T0,
        failed_extreme=90.0 if side == "long" else 110.0,
        range_midpoint=100.0,
    )
    expected = (
        90.0 - multiplier * 5.0
        if side == "long"
        else 110.0 + multiplier * 5.0
    )
    assert out.hard_stop_price == pytest.approx(expected)
    assert out.first_target_price == pytest.approx(100.0)
    assert out.time_stop_deadline_utc == T0 + deadline
    assert out.structure_invalidation_level is None


def test_zn_failed_break_stop_is_tick_aligned_and_away_from_entry() -> None:
    out = build_exit_geometry(
        playbook("pb_rates_failed_v1_3"),
        side="short",
        entry_price=112.0,
        atr=0.031,
        filled_at_utc=T0,
        failed_extreme=112.06,
        range_midpoint=112.0,
    )
    ticks = out.hard_stop_price / US10Y_TICK_POINTS
    assert ticks == pytest.approx(round(ticks))
    assert out.hard_stop_price >= 112.06 + 1.2 * 0.031


@pytest.mark.parametrize(
    "playbook_id",
    ("pb_fx_range_v1_3", "pb_eq_range_v1_3"),
)
def test_family_c_preserves_target_and_time_but_refuses_to_invent_stop_anchor(
    playbook_id: str,
) -> None:
    rule = exit_rule(playbook_id)
    assert rule.stop_anchor is StopAnchor.UNBOUND
    assert rule.atr_multiplier == pytest.approx(1.0)
    assert rule.target_rule is TargetRule.RANGE_MIDPOINT
    assert rule.invalidation_rule is InvalidationRule.NONE

    out = build_exit_geometry(
        playbook(playbook_id),
        side="long",
        entry_price=100.0,
        atr=5.0,
        filled_at_utc=T0,
        range_midpoint=100.5,
    )
    assert out.hard_stop_price is None
    assert out.first_target_price == pytest.approx(100.5)
    assert out.time_stop_deadline_utc == T0 + timedelta(minutes=90)
    assert out.source_complete is False


def test_eth_rider_preserves_bound_stop_but_exposes_unbound_exitplan_fields() -> None:
    out = build_exit_geometry(
        playbook("pb_eth_rider_v1_2"),
        side="long",
        entry_price=100.0,
        atr=10.0,
        filled_at_utc=T0,
        prior_range_low=80.0,
    )
    assert out.hard_stop_price == pytest.approx(78.0)
    assert out.first_target_price is None
    assert out.structure_invalidation_level is None
    assert out.time_stop_deadline_utc is None
    assert out.source_complete is False
    assert "rider time-stop" in str(out.unresolved_reason)


def test_bench_playbook_cannot_materialize_exit_geometry() -> None:
    with pytest.raises(ValueError, match="BENCH"):
        build_exit_geometry(
            playbook("pb_fx_scalp_v1_2"),
            side="long",
            entry_price=1.10,
            atr=0.01,
            filled_at_utc=T0,
        )
