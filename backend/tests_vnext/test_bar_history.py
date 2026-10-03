from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bar_history import ClosedBarHistory
from aether_vnext.bars import Bar


UTC = timezone.utc
MINUTE = timedelta(minutes=1)


def _bar(
    minute: int,
    *,
    asset_id: str = "btc",
    interval: timedelta = MINUTE,
    close: float | None = None,
) -> Bar:
    opened = datetime(2026, 9, 27, 6, minute, tzinfo=UTC)
    closed = opened + interval
    price = 100.0 + minute if close is None else float(close)
    return Bar(
        asset_id=asset_id,
        interval=interval,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=price - 0.5,
        high=price + 0.5,
        low=price - 1.0,
        close=price,
        volume=10.0 + minute,
        first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=closed - timedelta(microseconds=1),
        print_count=2,
        source_id="kraken_public_trade",
    )


def test_history_keeps_only_completed_bars_in_order() -> None:
    history = ClosedBarHistory(
        asset_id="btc",
        interval=MINUTE,
        max_bars=3,
    )

    history.append(_bar(30))
    history.append(_bar(31))
    history.append(_bar(32))

    snapshot = history.snapshot()
    assert snapshot.count == 3
    assert tuple(bar.bucket_open_utc.minute for bar in snapshot.bars) == (
        30,
        31,
        32,
    )
    assert snapshot.latest == _bar(32)
    assert history.last(2) == (_bar(31), _bar(32))


def test_history_evicts_oldest_bar_at_capacity_without_synthesizing_bars() -> None:
    history = ClosedBarHistory(
        asset_id="btc",
        interval=MINUTE,
        max_bars=2,
    )
    history.append(_bar(30))
    history.append(_bar(32))
    history.append(_bar(35))

    # Gaps are valid because empty buckets are not synthesized.
    assert tuple(bar.bucket_open_utc.minute for bar in history.snapshot().bars) == (
        32,
        35,
    )


def test_history_rejects_duplicate_or_out_of_order_bars() -> None:
    history = ClosedBarHistory(
        asset_id="btc",
        interval=MINUTE,
        max_bars=4,
    )
    history.append(_bar(31))

    with pytest.raises(ValueError, match="strictly increasing"):
        history.append(_bar(31))

    with pytest.raises(ValueError, match="strictly increasing"):
        history.append(_bar(30))


def test_history_rejects_wrong_asset_interval_or_not_closed_bar() -> None:
    history = ClosedBarHistory(
        asset_id="btc",
        interval=MINUTE,
        max_bars=4,
    )

    with pytest.raises(ValueError, match="asset_id"):
        history.append(_bar(30, asset_id="eth"))

    with pytest.raises(ValueError, match="interval"):
        history.append(
            _bar(
                30,
                interval=timedelta(minutes=5),
            )
        )

    bad = _bar(30)
    bad = Bar(
        asset_id=bad.asset_id,
        interval=bad.interval,
        bucket_open_utc=bad.bucket_open_utc,
        bucket_close_utc=bad.bucket_close_utc,
        open=bad.open,
        high=bad.high,
        low=bad.low,
        close=bad.close,
        volume=bad.volume,
        first_exchange_ts=bad.first_exchange_ts,
        last_exchange_ts=bad.bucket_close_utc,
        print_count=bad.print_count,
        source_id=bad.source_id,
    )
    with pytest.raises(ValueError, match="last_exchange_ts"):
        history.append(bad)
