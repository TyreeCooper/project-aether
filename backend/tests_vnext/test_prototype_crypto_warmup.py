from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.reference_prototype_history import COINBASE_SOURCE_ID
from aether_vnext.prototype_crypto_warmup import (
    MIN_RECENT_KRAKEN_HOURLY_BARS,
    assemble_prototype_crypto_warmup,
)
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar


UTC = timezone.utc
START = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


def _series(
    *,
    asset_id: str,
    interval: timedelta,
    count: int,
    start: datetime,
    source_id: str,
    base: float,
    drift: float,
    last_jump: float = 0.0,
) -> tuple[PrototypeMarketBar, ...]:
    rows = []
    for i in range(count):
        opened = start + i * interval
        close = base + drift * i + (last_jump if i == count - 1 else 0.0)
        open_ = close - max(0.1, abs(drift))
        rows.append(
            PrototypeMarketBar(
                asset_id=asset_id,
                interval_seconds=int(interval.total_seconds()),
                bucket_open_utc=opened,
                bucket_close_utc=opened + interval,
                open=open_,
                high=max(open_, close) + 1.0,
                low=min(open_, close) - 1.0,
                close=close,
                volume=10.0,
                trade_count=0 if source_id == COINBASE_SOURCE_ID else 20,
                source_id=source_id,
                source_ref=f"test:{source_id}",
                available_at_utc=opened + interval,
            )
        )
    return tuple(rows)


def test_hybrid_warmup_uses_reference_only_before_kraken_window() -> None:
    reference = _series(
        asset_id="btc",
        interval=timedelta(hours=1),
        count=2400,
        start=START,
        source_id=COINBASE_SOURCE_ID,
        base=90_000.0,
        drift=0.2,
    )
    kraken_start = START + timedelta(hours=1680)
    kraken = _series(
        asset_id="btc",
        interval=timedelta(hours=1),
        count=720,
        start=kraken_start,
        source_id=KRAKEN_DAILY_SOURCE_ID,
        base=90_336.0,
        drift=0.2,
        last_jump=100.0,
    )
    daily_start = START - timedelta(days=120)
    daily = _series(
        asset_id="btc",
        interval=timedelta(days=1),
        count=120,
        start=daily_start,
        source_id=KRAKEN_DAILY_SOURCE_ID,
        base=80_000.0,
        drift=100.0,
    )

    out = assemble_prototype_crypto_warmup(
        asset_id="btc",
        historical_reference_hourly=reference,
        kraken_hourly=kraken,
        asset_kraken_daily=daily,
        btc_kraken_daily=daily,
        as_of_utc=kraken[-1].bucket_close_utc,
    )

    assert out.kraken_hourly_bar_count == 720
    assert out.reference_hourly_bar_count == 1680
    assert len(out.hourly_bars) == 2400
    assert all(
        row.source_id == KRAKEN_DAILY_SOURCE_ID
        for row in out.hourly_bars[-21:]
    )
    assert out.feature_snapshot.prior_20h_high == max(
        row.high for row in kraken[-21:-1]
    )
    assert out.feature_snapshot.volatility.reference_count > 0


def test_hybrid_warmup_refuses_short_kraken_decision_window() -> None:
    reference = _series(
        asset_id="eth",
        interval=timedelta(hours=1),
        count=2400,
        start=START,
        source_id=COINBASE_SOURCE_ID,
        base=3_000.0,
        drift=0.01,
    )
    kraken = _series(
        asset_id="eth",
        interval=timedelta(hours=1),
        count=MIN_RECENT_KRAKEN_HOURLY_BARS - 1,
        start=START + timedelta(hours=1801),
        source_id=KRAKEN_DAILY_SOURCE_ID,
        base=3_018.0,
        drift=0.01,
    )
    daily = _series(
        asset_id="eth",
        interval=timedelta(days=1),
        count=60,
        start=START - timedelta(days=60),
        source_id=KRAKEN_DAILY_SOURCE_ID,
        base=2_500.0,
        drift=2.0,
    )
    btc_daily = _series(
        asset_id="btc",
        interval=timedelta(days=1),
        count=60,
        start=START - timedelta(days=60),
        source_id=KRAKEN_DAILY_SOURCE_ID,
        base=80_000.0,
        drift=50.0,
    )

    with pytest.raises(ValueError, match="completed Kraken hourly"):
        assemble_prototype_crypto_warmup(
            asset_id="eth",
            historical_reference_hourly=reference,
            kraken_hourly=kraken,
            asset_kraken_daily=daily,
            btc_kraken_daily=btc_daily,
            as_of_utc=kraken[-1].bucket_close_utc,
        )
