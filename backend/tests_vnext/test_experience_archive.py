from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.experience_archive import (
    CrisisRegimeArchiveEntry,
    CrisisRegimeArchiveQuery,
    retrieve_crisis_regime_archive,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 16, 0, tzinfo=UTC)


def _entry(
    archive_id: str,
    *,
    category: str = "liquidity_crisis",
    assets: tuple[str, ...] = ("btc",),
    regimes: tuple[str, ...] = ("risk_off",),
    recorded_offset: int = -5,
    synthetic: bool = False,
) -> CrisisRegimeArchiveEntry:
    return CrisisRegimeArchiveEntry(
        archive_id=archive_id,
        category=category,
        episode_ref=f"episode-{archive_id}",
        asset_ids=assets,
        regime_ids=regimes,
        started_at_utc=T0 - timedelta(hours=2),
        ended_at_utc=T0 - timedelta(hours=1),
        recorded_at_utc=T0 + timedelta(minutes=recorded_offset),
        source_record_ids=(f"source-{archive_id}",),
        synthetic=synthetic,
    )


def test_archive_query_enforces_point_in_time_availability() -> None:
    visible = _entry("visible", recorded_offset=-1)
    future = _entry("future", recorded_offset=1)

    result = retrieve_crisis_regime_archive(
        query=CrisisRegimeArchiveQuery(as_of_utc=T0),
        entries=(future, visible),
    )

    assert tuple(row.archive_id for row in result) == ("visible",)
    assert result[0].research_only is True


def test_archive_query_uses_only_explicit_category_asset_and_regime_filters() -> None:
    wanted = _entry(
        "wanted",
        category="scheduled_macro_surprise",
        assets=("btc", "eth"),
        regimes=("risk_off", "high_vol"),
        recorded_offset=-2,
    )
    wrong_category = _entry(
        "wrong-category",
        category="regulatory_shock",
        assets=("btc",),
        regimes=("risk_off",),
        recorded_offset=-1,
    )
    wrong_asset = _entry(
        "wrong-asset",
        category="scheduled_macro_surprise",
        assets=("mes",),
        regimes=("risk_off",),
        recorded_offset=-3,
    )

    result = retrieve_crisis_regime_archive(
        query=CrisisRegimeArchiveQuery(
            as_of_utc=T0,
            categories=("scheduled_macro_surprise",),
            asset_ids=("btc",),
            regime_ids=("risk_off",),
        ),
        entries=(wrong_category, wrong_asset, wanted),
    )

    assert tuple(row.archive_id for row in result) == ("wanted",)


def test_synthetic_episode_remains_labeled_and_research_only() -> None:
    entry = _entry("synthetic", synthetic=True)
    assert entry.synthetic is True
    assert entry.research_only is True

    with pytest.raises(ValueError, match="research_only"):
        CrisisRegimeArchiveEntry(
            archive_id="bad",
            category="liquidity_crisis",
            episode_ref="episode-bad",
            asset_ids=("btc",),
            regime_ids=("risk_off",),
            started_at_utc=T0 - timedelta(hours=2),
            ended_at_utc=T0 - timedelta(hours=1),
            recorded_at_utc=T0,
            source_record_ids=("source-bad",),
            research_only=False,
        )


def test_archive_rejects_unknown_category_and_reversed_time() -> None:
    with pytest.raises(ValueError, match="invalid crisis/regime category"):
        _entry("bad-category", category="invented")

    with pytest.raises(ValueError, match="time range is reversed"):
        CrisisRegimeArchiveEntry(
            archive_id="bad-time",
            category="liquidity_crisis",
            episode_ref="episode-bad-time",
            asset_ids=("btc",),
            regime_ids=("risk_off",),
            started_at_utc=T0,
            ended_at_utc=T0 - timedelta(minutes=1),
            recorded_at_utc=T0,
            source_record_ids=("source-bad-time",),
        )
