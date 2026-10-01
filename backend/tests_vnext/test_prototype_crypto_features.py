from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.runtime_product_policy import runtime_playbook_for_product

from aether_vnext.prototype_crypto_features import (
    CRYPTO_BREAKOUT_LOOKBACK_BARS,
    build_prototype_crypto_features,
)
from aether_vnext.prototype_market_history import PrototypeMarketBar


UTC = timezone.utc
START = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)


def _bars(
    *,
    asset_id: str,
    interval: timedelta,
    count: int,
    start: datetime,
    base: float,
    drift: float,
    last_jump: float = 0.0,
) -> tuple[PrototypeMarketBar, ...]:
    rows: list[PrototypeMarketBar] = []
    for i in range(count):
        opened = start + i * interval
        close = base + drift * i
        if i == count - 1:
            close += last_jump
        open_ = close - max(1.0, abs(drift))
        high = max(open_, close) + 2.0
        low = min(open_, close) - 2.0
        rows.append(
            PrototypeMarketBar(
                asset_id=asset_id,
                interval_seconds=int(interval.total_seconds()),
                bucket_open_utc=opened,
                bucket_close_utc=opened + interval,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=10.0 + i,
                trade_count=100 + i,
                source_id="kraken_ohlcvt_archive",
                source_ref="test-reviewed-history",
                available_at_utc=opened + interval,
            )
        )
    return tuple(rows)


def test_crypto_feature_boundary_uses_frozen_20_closed_hour_breakout() -> None:
    hourly = _bars(
        asset_id="btc",
        interval=timedelta(hours=1),
        count=(24 * 91) + 20,
        start=START,
        base=90_000.0,
        drift=1.0,
        last_jump=100.0,
    )
    daily = _bars(
        asset_id="btc",
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=80_000.0,
        drift=100.0,
    )
    as_of = hourly[-1].bucket_close_utc

    out = build_prototype_crypto_features(
        asset_id="btc",
        hourly_bars=hourly,
        asset_daily_bars=daily,
        btc_daily_bars=daily,
        as_of_utc=as_of,
    )

    assert CRYPTO_BREAKOUT_LOOKBACK_BARS == 20
    expected_high = max(bar.high for bar in hourly[-21:-1])
    expected_low = min(bar.low for bar in hourly[-21:-1])
    assert out.prior_20h_high == expected_high
    assert out.prior_20h_low == expected_low
    assert out.close > out.prior_20h_high
    assert out.daily_ema20 > out.daily_ema50
    assert out.btc_daily_close > out.btc_daily_ema50
    assert out.volatility.reference_count > 0
    assert 0.0 <= out.volatility.percentile <= 100.0


def test_eth_uses_own_daily_trend_and_btc_daily_market_regime() -> None:
    hourly = _bars(
        asset_id="eth",
        interval=timedelta(hours=1),
        count=(24 * 91) + 20,
        start=START,
        base=3_000.0,
        drift=0.05,
        last_jump=20.0,
    )
    eth_daily = _bars(
        asset_id="eth",
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=2_000.0,
        drift=5.0,
    )
    btc_daily = _bars(
        asset_id="btc",
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=80_000.0,
        drift=100.0,
    )

    out = build_prototype_crypto_features(
        asset_id="eth",
        hourly_bars=hourly,
        asset_daily_bars=eth_daily,
        btc_daily_bars=btc_daily,
        as_of_utc=hourly[-1].bucket_close_utc,
    )

    assert out.asset_id == "eth"
    assert out.daily_ema20 > out.daily_ema50
    assert out.btc_daily_close > out.btc_daily_ema50


def test_feature_boundary_fails_closed_without_90_day_warmup() -> None:
    hourly = _bars(
        asset_id="btc",
        interval=timedelta(hours=1),
        count=720,
        start=START,
        base=90_000.0,
        drift=1.0,
    )
    daily = _bars(
        asset_id="btc",
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=80_000.0,
        drift=100.0,
    )

    with pytest.raises(ValueError, match="pre-window RV14 warm-up"):
        build_prototype_crypto_features(
            asset_id="btc",
            hourly_bars=hourly,
            asset_daily_bars=daily,
            btc_daily_bars=daily,
            as_of_utc=hourly[-1].bucket_close_utc,
        )


def test_feature_boundary_rejects_future_or_unavailable_bar() -> None:
    hourly = _bars(
        asset_id="btc",
        interval=timedelta(hours=1),
        count=(24 * 91) + 20,
        start=START,
        base=90_000.0,
        drift=1.0,
    )
    daily = _bars(
        asset_id="btc",
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=80_000.0,
        drift=100.0,
    )

    with pytest.raises(ValueError, match="future prototype bar"):
        build_prototype_crypto_features(
            asset_id="btc",
            hourly_bars=hourly,
            asset_daily_bars=daily,
            btc_daily_bars=daily,
            as_of_utc=hourly[-1].bucket_open_utc,
        )



def test_dynamic_kraken_asset_uses_same_crypto_feature_parameters() -> None:
    asset_id = "kraken:solusd"
    hourly = _bars(
        asset_id=asset_id,
        interval=timedelta(hours=1),
        count=(24 * 91) + 20,
        start=START,
        base=140.0,
        drift=0.01,
        last_jump=10.0,
    )
    asset_daily = _bars(
        asset_id=asset_id,
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=100.0,
        drift=0.5,
    )
    btc_daily = _bars(
        asset_id="btc",
        interval=timedelta(days=1),
        count=120,
        start=START - timedelta(days=120),
        base=80_000.0,
        drift=100.0,
    )
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "execution_symbol": "SOLUSD",
            "asset_class": "spot_crypto",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.02,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15000,
    )
    assert projection.product is not None
    spec = runtime_playbook_for_product(
        projection.product,
        playbook_id="pb_crypto_swing_v1_2",
    )
    out = build_prototype_crypto_features(
        asset_id=asset_id,
        hourly_bars=hourly,
        asset_daily_bars=asset_daily,
        btc_daily_bars=btc_daily,
        as_of_utc=hourly[-1].bucket_close_utc,
        playbook_spec=spec,
    )
    assert out.asset_id == asset_id
    assert out.prior_20h_high == max(bar.high for bar in hourly[-21:-1])
    assert out.daily_ema20 > out.daily_ema50
    assert out.btc_daily_close > out.btc_daily_ema50
