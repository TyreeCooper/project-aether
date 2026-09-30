"""Prototype BTC/ETH closed-bar feature and Family-A evaluation boundary.

This module consumes only immutable prototype_market_bars rows. It preserves the
frozen crypto v1.2 mechanics:
- 1h trigger;
- prior 20 CLOSED 1h bars as the breakout reference;
- daily EMA20 > EMA50 asset trend;
- BTC daily close > BTC daily EMA50 market regime;
- ATR14 on the 1h trigger interval;
- RV14 percentile against the prior 90 calendar days of 1h completed bars.

No forming bar, future bar, unavailable bar, synthetic missing bucket, order, fill,
or Phase-18 evidence is created here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from aether_vnext.bar_features import PriorClosedBarRange, prior_closed_bar_range
from aether_vnext.family_a import FamilyAEvaluation, FamilyAContext, evaluate_family_a_structure
from aether_vnext.indicator_convention import atr14, ema20, ema50, realized_vol14
from aether_vnext.playbooks import playbook
from aether_vnext.prototype_market_history import PrototypeMarketBar
from aether_vnext.volatility_percentile import (
    VOLATILITY_PERCENTILE_CONVENTION_VERSION,
    VOLATILITY_PERCENTILE_WINDOW,
    RV14_REQUIRED_CLOSES,
    VolatilityPercentileSnapshot,
    empirical_midrank_percentile,
)


CRYPTO_TRIGGER_INTERVAL = timedelta(hours=1)
CRYPTO_TREND_INTERVAL = timedelta(days=1)
CRYPTO_BREAKOUT_LOOKBACK_BARS = 20
CRYPTO_PLAYBOOK_ID = "pb_crypto_swing_v1_2"


@dataclass(frozen=True, slots=True)
class PrototypeCryptoFeatureSnapshot:
    asset_id: str
    trigger_close_utc: datetime
    close: float
    atr14: float
    prior_20h_high: float
    prior_20h_low: float
    daily_ema20: float
    daily_ema50: float
    btc_daily_close: float
    btc_daily_ema50: float
    volatility: VolatilityPercentileSnapshot
    family_a: FamilyAEvaluation

    @property
    def watch_eligible(self) -> bool:
        return self.family_a.watch_eligible


def _pit_rows(
    bars: Sequence[PrototypeMarketBar],
    *,
    asset_id: str,
    interval: timedelta,
    as_of_utc: datetime,
    minimum: int,
) -> tuple[PrototypeMarketBar, ...]:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    rows = tuple(bars)
    if len(rows) < minimum:
        raise ValueError(f"at least {minimum} completed prototype bars are required")

    prior_open: datetime | None = None
    prior_close: datetime | None = None
    for bar in rows:
        if bar.asset_id != asset_id:
            raise ValueError("prototype bar asset mismatch")
        if bar.interval != interval:
            raise ValueError("prototype bar interval mismatch")
        if bar.bucket_close_utc > as_of_utc:
            raise ValueError("future prototype bar cannot enter features")
        if bar.available_at_utc > as_of_utc:
            raise ValueError("unavailable prototype bar cannot enter features")
        if prior_open is not None and bar.bucket_open_utc <= prior_open:
            raise ValueError("prototype bars must be strictly ordered")
        if prior_close is not None and bar.bucket_close_utc <= prior_close:
            raise ValueError("prototype bar closes must be strictly ordered")
        prior_open = bar.bucket_open_utc
        prior_close = bar.bucket_close_utc
    return rows


def _prototype_volatility_percentile(
    rows: tuple[PrototypeMarketBar, ...],
) -> VolatilityPercentileSnapshot:
    trigger_close = rows[-1].bucket_close_utc
    window_start = trigger_close - VOLATILITY_PERCENTILE_WINDOW

    pre_window = tuple(
        bar for bar in rows[:-1]
        if bar.bucket_close_utc <= window_start
    )
    if len(pre_window) < RV14_REQUIRED_CLOSES:
        raise ValueError(
            "insufficient pre-window RV14 warm-up for complete 90-day reference"
        )

    current_rv = realized_vol14(rows)
    reference: list[float] = []
    for end_index in range(RV14_REQUIRED_CLOSES - 1, len(rows) - 1):
        evaluation_close = rows[end_index].bucket_close_utc
        if not (window_start <= evaluation_close < trigger_close):
            continue
        start_index = end_index - (RV14_REQUIRED_CLOSES - 1)
        reference.append(
            realized_vol14(rows[start_index : end_index + 1])
        )
    percentile, less, equal = empirical_midrank_percentile(
        current_rv,
        reference,
    )
    return VolatilityPercentileSnapshot(
        asset_id=rows[-1].asset_id,
        interval=CRYPTO_TRIGGER_INTERVAL,
        trigger_close_utc=trigger_close,
        window_start_utc=window_start,
        window_end_exclusive_utc=trigger_close,
        current_realized_vol14=current_rv,
        reference_count=len(reference),
        less_count=less,
        equal_count=equal,
        percentile=percentile,
        convention_version=VOLATILITY_PERCENTILE_CONVENTION_VERSION,
    )


def build_prototype_crypto_features(
    *,
    asset_id: str,
    hourly_bars: Sequence[PrototypeMarketBar],
    asset_daily_bars: Sequence[PrototypeMarketBar],
    btc_daily_bars: Sequence[PrototypeMarketBar],
    as_of_utc: datetime,
) -> PrototypeCryptoFeatureSnapshot:
    asset = str(asset_id).strip().lower()
    if asset not in {"btc", "eth"}:
        raise ValueError("prototype crypto features support btc/eth only")

    hourly = _pit_rows(
        hourly_bars,
        asset_id=asset,
        interval=CRYPTO_TRIGGER_INTERVAL,
        as_of_utc=as_of_utc,
        minimum=CRYPTO_BREAKOUT_LOOKBACK_BARS + 1,
    )
    trigger_close = hourly[-1].bucket_close_utc

    asset_daily = _pit_rows(
        asset_daily_bars,
        asset_id=asset,
        interval=CRYPTO_TREND_INTERVAL,
        as_of_utc=trigger_close,
        minimum=50,
    )
    btc_daily = _pit_rows(
        btc_daily_bars,
        asset_id="btc",
        interval=CRYPTO_TREND_INTERVAL,
        as_of_utc=trigger_close,
        minimum=50,
    )

    prior: PriorClosedBarRange = prior_closed_bar_range(
        hourly,
        lookback_bars=CRYPTO_BREAKOUT_LOOKBACK_BARS,
    )
    volatility = _prototype_volatility_percentile(hourly)
    asset_ema20 = ema20(asset_daily)
    asset_ema50 = ema50(asset_daily)
    btc_ema50 = ema50(btc_daily)
    btc_close = float(btc_daily[-1].close)

    evaluation = evaluate_family_a_structure(
        playbook(CRYPTO_PLAYBOOK_ID),
        asset_id=asset,
        side="long",
        context=FamilyAContext(
            close=float(hourly[-1].close),
            volatility_percentile=volatility.percentile,
            reference_high=prior.high,
            reference_low=prior.low,
            trend_ema20=asset_ema20,
            trend_ema50=asset_ema50,
            btc_daily_close=btc_close,
            btc_daily_ema50=btc_ema50,
        ),
    )

    return PrototypeCryptoFeatureSnapshot(
        asset_id=asset,
        trigger_close_utc=trigger_close,
        close=float(hourly[-1].close),
        atr14=atr14(hourly),
        prior_20h_high=prior.high,
        prior_20h_low=prior.low,
        daily_ema20=asset_ema20,
        daily_ema50=asset_ema50,
        btc_daily_close=btc_close,
        btc_daily_ema50=btc_ema50,
        volatility=volatility,
        family_a=evaluation,
    )
