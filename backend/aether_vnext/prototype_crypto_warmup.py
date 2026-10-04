"""Source-separated prototype warm-up assembly for crypto PAPER trading.

The recent decision-critical window remains direct Kraken:
- trigger/ATR/prior-20 structure uses recent Kraken hourly bars;
- daily trend and BTC market regime use Kraken daily bars.

Older historical reference bars may extend the 90-day RV14 percentile window only
when they precede the available direct Kraken hourly window. Reference history never
overwrites a Kraken decision bar, never becomes executable market authority, and
never becomes Phase-18 evidence. Source provenance remains attached to every bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from aether_vnext.prototype_crypto_features import (
    CRYPTO_BREAKOUT_LOOKBACK_BARS,
    CRYPTO_TREND_INTERVAL,
    CRYPTO_TRIGGER_INTERVAL,
    PrototypeCryptoFeatureSnapshot,
    build_prototype_crypto_features,
)
from aether_vnext.playbooks import PlaybookSpec
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar
from aether_vnext.volatility_percentile import (
    RV14_REQUIRED_CLOSES,
    VOLATILITY_PERCENTILE_WINDOW,
)


MIN_RECENT_KRAKEN_HOURLY_BARS = CRYPTO_BREAKOUT_LOOKBACK_BARS + 1
MIN_KRAKEN_DAILY_BARS = 50


@dataclass(frozen=True, slots=True)
class PrototypeCryptoWarmup:
    asset_id: str
    hourly_bars: tuple[PrototypeMarketBar, ...]
    asset_daily_bars: tuple[PrototypeMarketBar, ...]
    btc_daily_bars: tuple[PrototypeMarketBar, ...]
    trigger_close_utc: datetime
    reference_hourly_bar_count: int
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
    historical_reference_hourly: Sequence[PrototypeMarketBar],
    kraken_hourly: Sequence[PrototypeMarketBar],
    asset_kraken_daily: Sequence[PrototypeMarketBar],
    btc_kraken_daily: Sequence[PrototypeMarketBar],
    as_of_utc: datetime,
    playbook_spec: PlaybookSpec | None = None,
) -> PrototypeCryptoWarmup:
    asset = str(asset_id).strip().lower()
    if not asset:
        raise ValueError("asset_id is required")
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    reference = _ordered_unique(
        historical_reference_hourly,
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

    trigger_close = kr[-1].bucket_close_utc
    if trigger_close > as_of_utc:
        raise ValueError("latest Kraken hourly bar cannot be in the future")

    earliest_kraken_open = kr[0].bucket_open_utc
    older_reference = tuple(
        row for row in reference
        if row.bucket_open_utc < earliest_kraken_open
        and row.bucket_close_utc <= trigger_close
    )
    # Kraken always wins overlap/current decision-time bars.
    hourly = (*older_reference, *kr)

    if len(hourly) < CRYPTO_BREAKOUT_LOOKBACK_BARS + 1:
        raise ValueError("insufficient hourly warm-up for crypto structure")

    window_start = trigger_close - VOLATILITY_PERCENTILE_WINDOW
    pre_window = tuple(
        row for row in hourly[:-1]
        if row.bucket_close_utc <= window_start
    )
    if len(pre_window) < RV14_REQUIRED_CLOSES:
        raise ValueError(
            "historical warm-up lacks 15 pre-window hourly bars for 90-day RV14 reference"
        )

    # The entire 20-bar structure/ATR decision window must remain direct Kraken.
    decision_window = hourly[-(CRYPTO_BREAKOUT_LOOKBACK_BARS + 1):]
    if any(row.source_id != KRAKEN_DAILY_SOURCE_ID for row in decision_window):
        raise ValueError("crypto decision window must remain Kraken-only")

    feature_snapshot = build_prototype_crypto_features(
        asset_id=asset,
        hourly_bars=hourly,
        asset_daily_bars=asset_daily,
        btc_daily_bars=btc_daily,
        as_of_utc=trigger_close,
        playbook_spec=playbook_spec,
    )

    return PrototypeCryptoWarmup(
        asset_id=asset,
        hourly_bars=tuple(hourly),
        asset_daily_bars=asset_daily,
        btc_daily_bars=btc_daily,
        trigger_close_utc=trigger_close,
        reference_hourly_bar_count=len(older_reference),
        kraken_hourly_bar_count=len(kr),
        feature_snapshot=feature_snapshot,
    )
