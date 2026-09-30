"""Hybrid prototype warm-up assembly for BTC/ETH PAPER trading.

The recent decision-critical window remains Kraken:
- trigger/ATR/prior-20 structure uses recent Kraken hourly bars;
- daily trend and BTC market regime use Kraken daily bars.

Older Coinbase hourly candles may extend the 90-day RV14 percentile reference only
when they precede the available Kraken hourly window. Coinbase never overwrites a
Kraken bar, never becomes the execution-market authority, and never becomes Phase-18
evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from aether_vnext.coinbase_prototype_history import COINBASE_SOURCE_ID
from aether_vnext.prototype_crypto_features import (
    CRYPTO_BREAKOUT_LOOKBACK_BARS,
    CRYPTO_TREND_INTERVAL,
    CRYPTO_TRIGGER_INTERVAL,
    PrototypeCryptoFeatureSnapshot,
    build_prototype_crypto_features,
)
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar
from aether_vnext.volatility_percentile import (
    RV14_REQUIRED_CLOSES,
    VOLATILITY_PERCENTILE_WINDOW,
)


MIN_RECENT_KRAKEN_HOURLY_BARS = 600
MIN_KRAKEN_DAILY_BARS = 50


@dataclass(frozen=True, slots=True)
class PrototypeCryptoWarmup:
    asset_id: str
    hourly_bars: tuple[PrototypeMarketBar, ...]
    asset_daily_bars: tuple[PrototypeMarketBar, ...]
    btc_daily_bars: tuple[PrototypeMarketBar, ...]
    trigger_close_utc: datetime
    coinbase_reference_bar_count: int
    kraken_hourly_bar_count: int
    feature_snapshot: PrototypeCryptoFeatureSnapshot


def _ordered_unique(
    rows: Sequence[PrototypeMarketBar],
    *,
    asset_id: str,
    interval: timedelta,
) -> tuple[PrototypeMarketBar, ...]:
    by_open: dict[datetime, PrototypeMarketBar] = {}
    for row in rows:
        if row.asset_id != asset_id:
            raise ValueError("warm-up row asset mismatch")
        if row.interval != interval:
            raise ValueError("warm-up row interval mismatch")
        prior = by_open.get(row.bucket_open_utc)
        if prior is not None and prior != row:
            raise ValueError("duplicate warm-up bar has conflicting content")
        by_open[row.bucket_open_utc] = row
    return tuple(by_open[key] for key in sorted(by_open))


def assemble_prototype_crypto_warmup(
    *,
    asset_id: str,
    coinbase_hourly: Sequence[PrototypeMarketBar],
    kraken_hourly: Sequence[PrototypeMarketBar],
    asset_kraken_daily: Sequence[PrototypeMarketBar],
    btc_kraken_daily: Sequence[PrototypeMarketBar],
    as_of_utc: datetime,
) -> PrototypeCryptoWarmup:
    asset = str(asset_id).strip().lower()
    if asset not in {"btc", "eth"}:
        raise ValueError("prototype warm-up supports btc/eth only")
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    cb = _ordered_unique(
        coinbase_hourly,
        asset_id=asset,
        interval=CRYPTO_TRIGGER_INTERVAL,
    )
    kr = _ordered_unique(
        kraken_hourly,
        asset_id=asset,
        interval=CRYPTO_TRIGGER_INTERVAL,
    )
    asset_daily = _ordered_unique(
        asset_kraken_daily,
        asset_id=asset,
        interval=CRYPTO_TREND_INTERVAL,
    )
    btc_daily = _ordered_unique(
        btc_kraken_daily,
        asset_id="btc",
        interval=CRYPTO_TREND_INTERVAL,
    )

    if len(kr) < MIN_RECENT_KRAKEN_HOURLY_BARS:
        raise ValueError(
            f"at least {MIN_RECENT_KRAKEN_HOURLY_BARS} completed Kraken hourly bars are required"
        )
    if len(asset_daily) < MIN_KRAKEN_DAILY_BARS:
        raise ValueError("at least 50 completed Kraken daily asset bars are required")
    if len(btc_daily) < MIN_KRAKEN_DAILY_BARS:
        raise ValueError("at least 50 completed Kraken BTC daily bars are required")
    if any(row.source_id != KRAKEN_DAILY_SOURCE_ID for row in kr):
        raise ValueError("recent hourly decision window must be direct Kraken REST bars")
    if any(row.source_id != KRAKEN_DAILY_SOURCE_ID for row in asset_daily):
        raise ValueError("asset daily trend must be direct Kraken REST bars")
    if any(row.source_id != KRAKEN_DAILY_SOURCE_ID for row in btc_daily):
        raise ValueError("BTC daily regime must be direct Kraken REST bars")
    if any(row.source_id != COINBASE_SOURCE_ID for row in cb):
        raise ValueError("older hourly warm-up rows must retain Coinbase provenance")

    trigger_close = kr[-1].bucket_close_utc
    if trigger_close > as_of_utc:
        raise ValueError("latest Kraken hourly bar cannot be in the future")

    earliest_kraken_open = kr[0].bucket_open_utc
    older_cb = tuple(
        row for row in cb
        if row.bucket_open_utc < earliest_kraken_open
        and row.bucket_close_utc <= trigger_close
    )
    # Kraken always wins overlap/current decision-time bars.
    hourly = (*older_cb, *kr)

    if len(hourly) < CRYPTO_BREAKOUT_LOOKBACK_BARS + 1:
        raise ValueError("insufficient hourly warm-up for crypto structure")

    window_start = trigger_close - VOLATILITY_PERCENTILE_WINDOW
    pre_window = tuple(
        row for row in hourly[:-1]
        if row.bucket_close_utc <= window_start
    )
    if len(pre_window) < RV14_REQUIRED_CLOSES:
        raise ValueError(
            "hybrid warm-up lacks 15 pre-window hourly bars for 90-day RV14 reference"
        )

    # The entire 20-bar structure/ATR decision window must be Kraken, not Coinbase.
    decision_window = hourly[-(CRYPTO_BREAKOUT_LOOKBACK_BARS + 1):]
    if any(row.source_id != KRAKEN_DAILY_SOURCE_ID for row in decision_window):
        raise ValueError("crypto decision window must remain Kraken-only")

    feature_snapshot = build_prototype_crypto_features(
        asset_id=asset,
        hourly_bars=hourly,
        asset_daily_bars=asset_daily,
        btc_daily_bars=btc_daily,
        as_of_utc=trigger_close,
    )

    return PrototypeCryptoWarmup(
        asset_id=asset,
        hourly_bars=tuple(hourly),
        asset_daily_bars=asset_daily,
        btc_daily_bars=btc_daily,
        trigger_close_utc=trigger_close,
        coinbase_reference_bar_count=len(older_cb),
        kraken_hourly_bar_count=len(kr),
        feature_snapshot=feature_snapshot,
    )
