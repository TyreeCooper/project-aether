from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp, sqrt

import pytest

from aether_vnext.bars import Bar
from aether_vnext.indicator_convention import (
    INDICATOR_CONVENTION_VERSION,
    atr14,
    ema20,
    ema50,
    realized_vol14,
)


UTC = timezone.utc
MINUTE = timedelta(minutes=1)


def _bar(
    index: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    asset_id: str = "btc",
    interval: timedelta = MINUTE,
) -> Bar:
    opened = datetime(2026, 9, 27, 0, 0, tzinfo=UTC) + index * interval
    return Bar(
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=opened,
        bucket_close_utc=opened + interval,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=opened + interval - timedelta(microseconds=1),
        print_count=1,
        source_id="test",
    )


def _flat_close_bar(index: int, close: float) -> Bar:
    return _bar(
        index,
        open_=close,
        high=close,
        low=close,
        close=close,
    )


def test_indicator_convention_version_is_frozen() -> None:
    assert INDICATOR_CONVENTION_VERSION == "aether_indicator_convention_v1"


def test_ema20_uses_sma_seed_then_recursive_alpha() -> None:
    bars = tuple(_flat_close_bar(i, float(i + 1)) for i in range(21))

    # SMA(1..20) = 10.5, then alpha=2/21 on close 21.
    expected = (2.0 / 21.0) * 21.0 + (19.0 / 21.0) * 10.5
    assert ema20(bars) == pytest.approx(expected)


def test_ema50_requires_fifty_completed_closes() -> None:
    bars = tuple(_flat_close_bar(i, 100.0 + i) for i in range(49))
    with pytest.raises(ValueError, match="at least 50"):
        ema50(bars)


def test_atr14_uses_true_range_seed_and_wilder_smoothing() -> None:
    bars = [_flat_close_bar(0, 100.0)]
    previous_close = 100.0

    # First 14 true ranges are exactly 2.0 -> initial ATR14 = 2.0.
    for index in range(1, 15):
        close = previous_close + 0.5
        bars.append(
            _bar(
                index,
                open_=previous_close,
                high=previous_close + 1.0,
                low=previous_close - 1.0,
                close=close,
            )
        )
        previous_close = close

    # Fifteenth TR is 4.0 -> Wilder update = (13*2 + 4)/14.
    bars.append(
        _bar(
            15,
            open_=previous_close,
            high=previous_close + 2.0,
            low=previous_close - 2.0,
            close=previous_close + 0.5,
        )
    )

    assert atr14(tuple(bars)) == pytest.approx(30.0 / 14.0)


def test_realized_vol14_is_nonannualized_trailing_log_return_norm() -> None:
    bars = tuple(
        _flat_close_bar(index, exp(index * 0.01))
        for index in range(15)
    )

    assert realized_vol14(bars) == pytest.approx(sqrt(14.0 * 0.01**2))


def test_realized_vol14_uses_only_trailing_fourteen_returns() -> None:
    bars = (
        _flat_close_bar(0, 1.0),
        _flat_close_bar(1, 10.0),
        *tuple(
            _flat_close_bar(index + 2, 10.0 * exp(index * 0.01))
            for index in range(14)
        ),
    )

    # The extreme 1 -> 10 move lies outside the trailing 15 bars.
    expected = sqrt(13.0 * 0.01**2)
    assert realized_vol14(bars) == pytest.approx(expected)


def test_indicator_math_rejects_mixed_assets() -> None:
    bars = tuple(_flat_close_bar(i, 100.0 + i) for i in range(19)) + (
        _bar(
            19,
            open_=120.0,
            high=120.0,
            low=120.0,
            close=120.0,
            asset_id="eth",
        ),
    )
    with pytest.raises(ValueError, match="asset_id"):
        ema20(bars)
