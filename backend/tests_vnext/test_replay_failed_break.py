from datetime import datetime, timedelta, timezone
import pytest

from aether_vnext.bars import Bar
from aether_vnext.playbooks import playbook
from aether_vnext.replay_failed_break import (
    FrozenBreakReference,
    ReplayReferenceKind,
    expected_family_b_reference_kind,
    reconstruct_family_b_state,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

def _bar(index, *, asset_id, interval, close):
    opened = T0 + index * interval
    closed = opened + interval
    return Bar(
        asset_id=asset_id, interval=interval,
        bucket_open_utc=opened, bucket_close_utc=closed,
        open=close, high=close + 0.5, low=close - 0.5, close=close,
        volume=1.0, first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=closed - timedelta(microseconds=1),
        print_count=1, source_id="reviewed-pit-bars",
    )

def _ref(asset_id, kind):
    return FrozenBreakReference(
        asset_id=asset_id, kind=kind, high=100.0, low=90.0, mid=95.0,
        frozen_at_utc=T0 - timedelta(hours=1), source_ref="reviewed-reference:v1",
    )

def test_reference_kinds_are_source_bound():
    assert expected_family_b_reference_kind(
        playbook("pb_crypto_failed_break_v1_3")
    ) is ReplayReferenceKind.PRIOR_20_CLOSED_BARS
    assert expected_family_b_reference_kind(
        playbook("pb_fx_failed_session_v1_3")
    ) is ReplayReferenceKind.PRIOR_COMPLETED_SESSION
    assert expected_family_b_reference_kind(
        playbook("pb_idx_failed_v1_3")
    ) is ReplayReferenceKind.PRIOR_OFFICIAL_RTH_DAY

def test_short_fade_reconstructs_break_and_later_close_back_inside():
    spec = playbook("pb_idx_failed_v1_3")
    rows = (
        _bar(0, asset_id="mes", interval=spec.trigger_interval, close=101.0),
        _bar(1, asset_id="mes", interval=spec.trigger_interval, close=100.5),
        _bar(2, asset_id="mes", interval=spec.trigger_interval, close=99.0),
    )
    state = reconstruct_family_b_state(
        spec, asset_id="mes", side="short", bars=rows,
        reference=_ref("mes", ReplayReferenceKind.PRIOR_OFFICIAL_RTH_DAY),
        break_bar_close_utc=rows[0].bucket_close_utc,
        counter_trend_condition=True,
    )
    assert state.break_printed is True
    assert state.bars_since_break == 2
    assert state.close_back_inside is True

def test_long_fade_reconstructs_down_break():
    spec = playbook("pb_rates_failed_v1_3")
    rows = (
        _bar(0, asset_id="us10y", interval=spec.trigger_interval, close=89.0),
        _bar(1, asset_id="us10y", interval=spec.trigger_interval, close=91.0),
    )
    state = reconstruct_family_b_state(
        spec, asset_id="us10y", side="long", bars=rows,
        reference=_ref("us10y", ReplayReferenceKind.PRIOR_20_CLOSED_BARS),
        break_bar_close_utc=rows[0].bucket_close_utc,
        counter_trend_condition=True,
    )
    assert state.break_printed is True
    assert state.bars_since_break == 1
    assert state.close_back_inside is True

def test_wrong_reference_kind_fails_closed():
    spec = playbook("pb_eq_failed_v1_3")
    rows = (
        _bar(0, asset_id="nvda", interval=spec.trigger_interval, close=101.0),
        _bar(1, asset_id="nvda", interval=spec.trigger_interval, close=99.0),
    )
    with pytest.raises(ValueError, match="wrong frozen reference kind"):
        reconstruct_family_b_state(
            spec, asset_id="nvda", side="short", bars=rows,
            reference=_ref("nvda", ReplayReferenceKind.PRIOR_20_CLOSED_BARS),
            break_bar_close_utc=rows[0].bucket_close_utc,
            counter_trend_condition=True, locate_ok=True,
        )

def test_reference_must_preexist_break_bar():
    spec = playbook("pb_fx_failed_session_v1_3")
    rows = (
        _bar(0, asset_id="eurusd", interval=spec.trigger_interval, close=101.0),
        _bar(1, asset_id="eurusd", interval=spec.trigger_interval, close=99.0),
    )
    reference = FrozenBreakReference(
        asset_id="eurusd", kind=ReplayReferenceKind.PRIOR_COMPLETED_SESSION,
        high=100.0, low=90.0, mid=95.0,
        frozen_at_utc=rows[0].bucket_close_utc, source_ref="late-reference",
    )
    with pytest.raises(ValueError, match="not available before break bar"):
        reconstruct_family_b_state(
            spec, asset_id="eurusd", side="short", bars=rows,
            reference=reference,
            break_bar_close_utc=rows[0].bucket_close_utc,
            counter_trend_condition=True,
        )
