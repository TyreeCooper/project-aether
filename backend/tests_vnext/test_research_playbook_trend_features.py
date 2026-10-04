from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.indicator_convention import ema20, ema50
from aether_vnext.playbook_trend_requirements import TrendRuleKind
from aether_vnext.research_bar_selection import PITResearchBarSlice
from aether_vnext.research_playbook_trend_features import (
    build_research_playbook_trend_features,
)
from aether_vnext.research_replay_features import ResearchFeatureBar
from aether_vnext.research_warehouse import ResearchBarRecord


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _selection(
    *,
    asset_id: str,
    interval: timedelta,
    count: int,
    unavailable_last: bool = False,
) -> PITResearchBarSlice:
    rows = []
    for index in range(count):
        opened = T0 + index * interval
        closed = opened + interval
        close = 100.0 + index * 0.25
        rows.append(
            ResearchBarRecord(
                research_bar_id=f"bar-{asset_id}-{index}",
                dataset_snapshot_id="dataset-1",
                asset_id=asset_id,
                interval_seconds=int(interval.total_seconds()),
                bucket_open_utc=opened,
                bucket_close_utc=closed,
                open=close - 0.1,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1.0,
                source_id="reviewed-history",
                source_data_version="v1",
                source_ref="reviewed-ref",
                available_at_utc=(
                    closed + timedelta(seconds=1)
                    if unavailable_last and index == count - 1
                    else closed
                ),
            )
        )
    return PITResearchBarSlice(
        dataset_snapshot_id="dataset-1",
        asset_id=asset_id,
        interval_seconds=int(interval.total_seconds()),
        as_of_utc=rows[-1].bucket_close_utc,
        start_at_utc=None,
        rows=tuple(rows),
    )


def _feature_rows(selection: PITResearchBarSlice) -> tuple[ResearchFeatureBar, ...]:
    return tuple(
        ResearchFeatureBar(
            research_bar_id=row.research_bar_id,
            asset_id=row.asset_id,
            interval=timedelta(seconds=row.interval_seconds),
            bucket_open_utc=row.bucket_open_utc,
            bucket_close_utc=row.bucket_close_utc,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            available_at_utc=row.available_at_utc,
            source_id=row.source_id,
        )
        for row in selection.rows
    )


def test_fx_intraday_builds_one_hour_slope_from_pit_research_rows() -> None:
    selection = _selection(
        asset_id="eurusd",
        interval=timedelta(hours=1),
        count=60,
    )
    result = build_research_playbook_trend_features(
        "pb_fx_intraday_v1_2",
        selection,
    )
    rows = _feature_rows(selection)

    assert result.rule_kind is TrendRuleKind.EMA20_SLOPE
    assert result.interval == timedelta(hours=1)
    assert result.ema20_current == pytest.approx(ema20(rows))
    assert result.ema20_previous == pytest.approx(ema20(rows[:-1]))
    assert result.ema50_current is None


def test_crypto_swing_builds_daily_level_pair_from_pit_research_rows() -> None:
    selection = _selection(
        asset_id="btc",
        interval=timedelta(days=1),
        count=60,
    )
    result = build_research_playbook_trend_features(
        "pb_crypto_swing_v1_2",
        selection,
    )
    rows = _feature_rows(selection)

    assert result.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL
    assert result.ema20_current == pytest.approx(ema20(rows))
    assert result.ema20_previous is None
    assert result.ema50_current == pytest.approx(ema50(rows))


def test_wrong_research_interval_fails_closed() -> None:
    selection = _selection(
        asset_id="mgc",
        interval=timedelta(minutes=15),
        count=60,
    )
    with pytest.raises(ValueError, match="interval does not match"):
        build_research_playbook_trend_features(
            "pb_metal_intraday_v1_2",
            selection,
        )


def test_unavailable_research_trend_bar_fails_closed() -> None:
    selection = _selection(
        asset_id="eurusd",
        interval=timedelta(hours=1),
        count=60,
        unavailable_last=True,
    )
    with pytest.raises(ValueError, match="unavailable research trend bar"):
        build_research_playbook_trend_features(
            "pb_fx_intraday_v1_2",
            selection,
        )


def test_asset_not_allowed_by_playbook_fails_closed() -> None:
    selection = _selection(
        asset_id="btc",
        interval=timedelta(hours=1),
        count=60,
    )
    with pytest.raises(ValueError, match="not allowed"):
        build_research_playbook_trend_features(
            "pb_fx_intraday_v1_2",
            selection,
        )
