from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.bars import Bar
from aether_vnext.volatility_percentile import (
    VOLATILITY_PERCENTILE_CONVENTION_VERSION,
    VolatilityPercentileSnapshot,
    empirical_midrank_percentile,
    realized_vol14_percentile_90d,
)


UTC = timezone.utc
HOUR = timedelta(hours=1)
T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


def _bar(
    index: int,
    *,
    close: float = 100.0,
    asset_id: str = "btc",
    last_at_close: bool = False,
) -> Bar:
    opened = T0 + index * HOUR
    closed = opened + HOUR
    return Bar(
        asset_id=asset_id,
        interval=HOUR,
        bucket_open_utc=opened,
        bucket_close_utc=closed,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        first_exchange_ts=opened + timedelta(seconds=1),
        last_exchange_ts=(
            closed
            if last_at_close
            else closed - timedelta(microseconds=1)
        ),
        print_count=1,
        source_id="reviewed-pit-bars",
    )


def test_midrank_ties_are_symmetric_without_interpolation() -> None:
    percentile, less, equal = empirical_midrank_percentile(
        2.0,
        (1.0, 2.0, 2.0, 4.0),
    )
    assert less == 1
    assert equal == 2
    assert percentile == pytest.approx(50.0)


def test_all_equal_distribution_maps_to_midpoint() -> None:
    percentile, less, equal = empirical_midrank_percentile(
        3.0,
        (3.0, 3.0, 3.0),
    )
    assert less == 0
    assert equal == 3
    assert percentile == pytest.approx(50.0)


def test_current_trigger_is_excluded_from_prior_90_day_distribution() -> None:
    count = 92 * 24
    bars = tuple(_bar(index) for index in range(count - 1)) + (
        _bar(count - 1, close=110.0),
    )
    result = realized_vol14_percentile_90d(
        bars,
        as_of_utc=bars[-1].bucket_close_utc,
    )

    assert result.current_realized_vol14 > 0.0
    assert result.reference_count > 0
    assert result.less_count == result.reference_count
    assert result.equal_count == 0
    assert result.percentile == pytest.approx(100.0)
    assert result.window_end_exclusive_utc == bars[-1].bucket_close_utc
    assert (
        result.convention_version
        == VOLATILITY_PERCENTILE_CONVENTION_VERSION
    )


def test_complete_window_requires_pre_window_rv14_warmup() -> None:
    bars = tuple(_bar(index) for index in range(90 * 24 + 1))
    with pytest.raises(ValueError, match="pre-window RV14 warm-up"):
        realized_vol14_percentile_90d(
            bars,
            as_of_utc=bars[-1].bucket_close_utc,
        )


def test_future_and_forming_bars_fail_closed() -> None:
    bars = tuple(_bar(index) for index in range(92 * 24))

    with pytest.raises(ValueError, match="future bar"):
        realized_vol14_percentile_90d(
            bars,
            as_of_utc=bars[-1].bucket_close_utc - timedelta(seconds=1),
        )

    forming = (*bars[:-1], _bar(len(bars) - 1, last_at_close=True))
    with pytest.raises(ValueError, match="forming/incomplete"):
        realized_vol14_percentile_90d(
            forming,
            as_of_utc=forming[-1].bucket_close_utc,
        )


def test_midrank_rejects_boolean_volatility_inputs() -> None:
    with pytest.raises(
        ValueError,
        match="current volatility must be numeric, not boolean",
    ):
        empirical_midrank_percentile(True, (1.0,))

    with pytest.raises(
        ValueError,
        match="reference volatility values must be numeric, not boolean",
    ):
        empirical_midrank_percentile(1.0, (False,))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "current_realized_vol14",
            True,
            "current_realized_vol14 must be numeric, not boolean",
        ),
        (
            "percentile",
            True,
            "percentile must be numeric, not boolean",
        ),
    ),
)
def test_volatility_snapshot_rejects_boolean_numerics(
    field: str,
    value: object,
    message: str,
) -> None:
    base = VolatilityPercentileSnapshot(
        asset_id="btc",
        interval=HOUR,
        trigger_close_utc=T0,
        window_start_utc=T0 - timedelta(days=90),
        window_end_exclusive_utc=T0,
        current_realized_vol14=1.0,
        reference_count=2,
        less_count=1,
        equal_count=0,
        percentile=50.0,
    )
    kwargs = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        VolatilityPercentileSnapshot(**kwargs)


def test_empty_midrank_reference_fails_closed() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        empirical_midrank_percentile(1.0, ())
