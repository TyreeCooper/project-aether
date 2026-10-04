from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bar_features import prior_closed_bar_range
from aether_vnext.indicator_convention import (
    atr14,
    ema20,
    ema50,
    realized_vol14,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ResearchMathBar:
    asset_id: str
    interval: timedelta
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float


def _bars(count: int = 60) -> tuple[ResearchMathBar, ...]:
    out = []
    for index in range(count):
        opened = T0 + index * HOUR
        close = 100.0 + index * 0.25
        out.append(
            ResearchMathBar(
                asset_id="btc",
                interval=HOUR,
                bucket_open_utc=opened,
                bucket_close_utc=opened + HOUR,
                open=close - 0.1,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
            )
        )
    return tuple(out)


def test_pure_indicator_math_accepts_completed_ohlc_without_exchange_fields() -> None:
    bars = _bars()

    assert ema20(bars) > 0.0
    assert ema50(bars) > 0.0
    assert atr14(bars) > 0.0
    assert realized_vol14(bars) >= 0.0


def test_prior_range_accepts_same_completed_ohlc_contract() -> None:
    bars = _bars()
    result = prior_closed_bar_range(
        bars,
        lookback_bars=20,
    )

    reference = bars[-21:-1]
    assert result.asset_id == "btc"
    assert result.high == pytest.approx(
        max(row.high for row in reference)
    )
    assert result.low == pytest.approx(
        min(row.low for row in reference)
    )
    assert result.first_bar == reference[0]
    assert result.last_bar == reference[-1]


def test_math_contract_still_rejects_mixed_asset_or_interval() -> None:
    bars = list(_bars())
    last = bars[-1]
    bars[-1] = ResearchMathBar(
        asset_id="eth",
        interval=last.interval,
        bucket_open_utc=last.bucket_open_utc,
        bucket_close_utc=last.bucket_close_utc,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
    )
    with pytest.raises(ValueError, match="asset_id"):
        ema20(tuple(bars))
