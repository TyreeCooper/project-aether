from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bars import Bar
from aether_vnext.indicator_convention import (
    INDICATOR_CONVENTION_VERSION,
    atr14,
    ema20,
    ema50,
    realized_vol14,
)
from aether_vnext.playbook_runtime import VolatilityBand
from aether_vnext.replay_features import (
    build_closed_bar_feature_snapshot,
    build_regime_ready_replay_features,
)


UTC = timezone.utc
MINUTE = timedelta(minutes=1)
T0 = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)


def _bar(
    index: int,
    *,
    asset_id: str = "btc",
    interval: timedelta = MINUTE,
    last_at_close: bool = False,
) -> Bar:
    opened = T0 + index * interval
    close = 100.0 + index * 0.25
    closed = opened + interval
    return Bar(
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
            if last_at_close
            else closed - timedelta(microseconds=1)
        ),
        print_count=2,
        source_id="reviewed-pit-bars",
    )


def _bars(count: int = 60) -> tuple[Bar, ...]:
    return tuple(_bar(index) for index in range(count))


def test_snapshot_matches_bound_indicator_math_without_choosing_regime() -> None:
    bars = _bars()
    as_of = bars[-1].bucket_close_utc

    result = build_closed_bar_feature_snapshot(
        bars,
        as_of_utc=as_of,
    )

    assert result.asset_id == "btc"
    assert result.interval == MINUTE
    assert result.bar_count == 60
    assert result.trigger_bar == bars[-1]
    assert result.close == pytest.approx(bars[-1].close)
    assert result.ema20_current == pytest.approx(ema20(bars))
    assert result.ema20_previous == pytest.approx(ema20(bars[:-1]))
    assert result.ema50_current == pytest.approx(ema50(bars))
    assert result.atr14_current == pytest.approx(atr14(bars))
    assert result.realized_vol14_current == pytest.approx(
        realized_vol14(bars)
    )
    assert result.prior_range is None
    assert (
        result.indicator_convention_version
        == INDICATOR_CONVENTION_VERSION
    )


def test_explicit_prior_range_excludes_trigger_bar() -> None:
    bars = _bars()

    result = build_closed_bar_feature_snapshot(
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
        prior_range_lookback=20,
    )

    assert result.prior_range is not None
    assert result.prior_range.lookback_bars == 20
    reference = bars[-21:-1]
    assert result.prior_range.high == pytest.approx(
        max(bar.high for bar in reference)
    )
    assert result.prior_range.low == pytest.approx(
        min(bar.low for bar in reference)
    )


def test_snapshot_refuses_future_bar() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="future bar"):
        build_closed_bar_feature_snapshot(
            bars,
            as_of_utc=bars[-1].bucket_close_utc - timedelta(seconds=1),
        )


def test_snapshot_refuses_forming_bar() -> None:
    bars = (*_bars(59), _bar(59, last_at_close=True))
    with pytest.raises(ValueError, match="forming/incomplete"):
        build_closed_bar_feature_snapshot(
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )


def test_snapshot_never_invents_range_lookback() -> None:
    bars = _bars()
    result = build_closed_bar_feature_snapshot(
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
        prior_range_lookback=None,
    )
    assert result.prior_range is None

    with pytest.raises(ValueError, match="must be positive"):
        build_closed_bar_feature_snapshot(
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
            prior_range_lookback=0,
        )


def test_snapshot_requires_enough_warmup_for_ema50() -> None:
    bars = _bars(49)
    with pytest.raises(ValueError, match="at least 50"):
        build_closed_bar_feature_snapshot(
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )


def test_mixed_asset_history_fails_closed_through_indicator_contract() -> None:
    bars = (*_bars(59), _bar(59, asset_id="eth"))
    with pytest.raises(ValueError, match="asset_id"):
        build_closed_bar_feature_snapshot(
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )



def test_regime_ready_features_bind_percentile_and_band_without_family_choice() -> None:
    hour = timedelta(hours=1)
    start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)

    def hourly_bar(index: int, close: float) -> Bar:
        opened = start + index * hour
        closed = opened + hour
        return Bar(
            asset_id="btc",
            interval=hour,
            bucket_open_utc=opened,
            bucket_close_utc=closed,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1.0,
            first_exchange_ts=opened + timedelta(seconds=1),
            last_exchange_ts=closed - timedelta(microseconds=1),
            print_count=1,
            source_id="reviewed-pit-bars",
        )

    count = 92 * 24
    bars = tuple(hourly_bar(index, 100.0) for index in range(count - 1)) + (
        hourly_bar(count - 1, 110.0),
    )

    result = build_regime_ready_replay_features(
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
        prior_range_lookback=20,
    )

    assert result.numerical.asset_id == "btc"
    assert result.numerical.prior_range is not None
    assert result.volatility.reference_count > 0
    assert result.volatility.percentile == pytest.approx(100.0)
    assert result.volatility_band is VolatilityBand.ABOVE_85


def test_regime_ready_features_fail_closed_without_full_90_day_history() -> None:
    bars = _bars(60)
    with pytest.raises(ValueError, match="pre-window RV14 warm-up"):
        build_regime_ready_replay_features(
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )
