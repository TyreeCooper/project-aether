from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bar_features import prior_closed_bar_range
from aether_vnext.bars import Bar


UTC = timezone.utc
MINUTE = timedelta(minutes=1)


def _bar(
    minute: int,
    *,
    high: float,
    low: float,
    close: float,
    asset_id: str = "btc",
    interval: timedelta = MINUTE,
) -> Bar:
    opened = datetime(2026, 9, 27, 7, minute, tzinfo=UTC)
    return Bar(
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=opened,
        bucket_close_utc=opened + interval,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=opened + interval - timedelta(microseconds=1),
        print_count=1,
        source_id="test",
    )


def test_prior_range_excludes_trigger_bar() -> None:
    bars = (
        _bar(30, high=101, low=99, close=100),
        _bar(31, high=103, low=98, close=102),
        _bar(32, high=102, low=97, close=101),
        _bar(33, high=150, low=50, close=149),
    )

    result = prior_closed_bar_range(bars, lookback_bars=3)

    assert result.lookback_bars == 3
    assert result.high == pytest.approx(103)
    assert result.low == pytest.approx(97)
    assert result.mid == pytest.approx(100)
    assert result.first_bar == bars[0]
    assert result.last_bar == bars[2]


def test_prior_range_uses_only_immediately_preceding_lookback() -> None:
    bars = (
        _bar(29, high=999, low=1, close=500),
        _bar(30, high=101, low=99, close=100),
        _bar(31, high=103, low=98, close=102),
        _bar(32, high=102, low=97, close=101),
        _bar(33, high=104, low=96, close=103),
    )

    result = prior_closed_bar_range(bars, lookback_bars=3)

    assert result.high == pytest.approx(103)
    assert result.low == pytest.approx(97)


def test_prior_range_requires_reference_bars_plus_trigger() -> None:
    bars = (
        _bar(30, high=101, low=99, close=100),
        _bar(31, high=103, low=98, close=102),
        _bar(32, high=102, low=97, close=101),
    )

    with pytest.raises(ValueError, match="insufficient"):
        prior_closed_bar_range(bars, lookback_bars=3)


def test_prior_range_rejects_mixed_asset_interval_or_order() -> None:
    bars = (
        _bar(30, high=101, low=99, close=100),
        _bar(31, high=103, low=98, close=102, asset_id="eth"),
        _bar(32, high=102, low=97, close=101),
    )
    with pytest.raises(ValueError, match="asset_id"):
        prior_closed_bar_range(bars, lookback_bars=2)

    mixed_interval = (
        _bar(30, high=101, low=99, close=100),
        _bar(
            31,
            high=103,
            low=98,
            close=102,
            interval=timedelta(minutes=5),
        ),
        _bar(32, high=102, low=97, close=101),
    )
    with pytest.raises(ValueError, match="interval"):
        prior_closed_bar_range(mixed_interval, lookback_bars=2)

    out_of_order = (
        _bar(31, high=103, low=98, close=102),
        _bar(30, high=101, low=99, close=100),
        _bar(32, high=102, low=97, close=101),
    )
    with pytest.raises(ValueError, match="strictly ordered"):
        prior_closed_bar_range(out_of_order, lookback_bars=2)
