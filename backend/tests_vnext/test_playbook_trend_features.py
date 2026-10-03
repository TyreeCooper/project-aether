from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bars import Bar
from aether_vnext.indicator_convention import ema20, ema50
from aether_vnext.playbook_trend_features import (
    build_playbook_trend_features,
)
from aether_vnext.playbook_trend_requirements import TrendRuleKind


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _bars(
    count: int,
    *,
    asset_id: str,
    interval: timedelta,
    last_at_close: bool = False,
) -> tuple[Bar, ...]:
    out = []
    for index in range(count):
        opened = T0 + index * interval
        closed = opened + interval
        close = 100.0 + index * 0.25
        out.append(
            Bar(
                asset_id=asset_id,
                interval=interval,
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=close - 0.10,
                high=close + 0.50,
                low=close - 0.50,
                close=close,
                volume=10.0 + index,
                first_exchange_ts=opened + timedelta(seconds=1),
                last_exchange_ts=(
                    closed
                    if last_at_close and index == count - 1
                    else closed - timedelta(microseconds=1)
                ),
                print_count=2,
                source_id="reviewed-pit-bars",
            )
        )
    return tuple(out)


def test_fx_intraday_builds_one_hour_ema20_slope() -> None:
    bars = _bars(
        60,
        asset_id="eurusd",
        interval=timedelta(hours=1),
    )
    result = build_playbook_trend_features(
        "pb_fx_intraday_v1_2",
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
    )

    assert result.rule_kind is TrendRuleKind.EMA20_SLOPE
    assert result.interval == timedelta(hours=1)
    assert result.ema20_current == pytest.approx(ema20(bars))
    assert result.ema20_previous == pytest.approx(ema20(bars[:-1]))
    assert result.ema50_current is None


def test_crypto_swing_builds_daily_ema_level_pair() -> None:
    bars = _bars(
        60,
        asset_id="btc",
        interval=timedelta(days=1),
    )
    result = build_playbook_trend_features(
        "pb_crypto_swing_v1_2",
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
    )

    assert result.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL
    assert result.interval == timedelta(days=1)
    assert result.ema20_current == pytest.approx(ema20(bars))
    assert result.ema20_previous is None
    assert result.ema50_current == pytest.approx(ema50(bars))


def test_same_interval_equity_trend_uses_fifteen_minute_bars() -> None:
    bars = _bars(
        50,
        asset_id="nvda",
        interval=timedelta(minutes=15),
    )
    result = build_playbook_trend_features(
        "pb_eq_swing_v1_2",
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
    )
    assert result.interval == timedelta(minutes=15)
    assert result.ema50_current == pytest.approx(ema50(bars))


def test_wrong_interval_fails_closed_instead_of_resampling() -> None:
    bars = _bars(
        60,
        asset_id="mgc",
        interval=timedelta(minutes=15),
    )
    with pytest.raises(ValueError, match="does not match"):
        build_playbook_trend_features(
            "pb_metal_intraday_v1_2",
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )


def test_future_bar_fails_closed() -> None:
    bars = _bars(
        60,
        asset_id="us10y",
        interval=timedelta(days=1),
    )
    with pytest.raises(ValueError, match="future bar"):
        build_playbook_trend_features(
            "pb_rates_swing_v1_2",
            bars,
            as_of_utc=bars[-1].bucket_close_utc - timedelta(seconds=1),
        )


def test_forming_bar_fails_closed() -> None:
    bars = _bars(
        60,
        asset_id="mcl",
        interval=timedelta(hours=1),
        last_at_close=True,
    )
    with pytest.raises(ValueError, match="forming/incomplete"):
        build_playbook_trend_features(
            "pb_energy_intraday_v1_2",
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )


def test_slope_rule_requires_previous_ema20_state() -> None:
    bars = _bars(
        20,
        asset_id="eurusd",
        interval=timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="at least 21"):
        build_playbook_trend_features(
            "pb_fx_intraday_v1_2",
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )


def test_level_rule_requires_ema50_warmup() -> None:
    bars = _bars(
        49,
        asset_id="nvda",
        interval=timedelta(minutes=15),
    )
    with pytest.raises(ValueError, match="at least 50"):
        build_playbook_trend_features(
            "pb_eq_intraday_v1_2",
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )
