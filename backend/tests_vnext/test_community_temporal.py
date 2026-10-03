from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.community_temporal import (
    CommunityWindow,
    NarrativeMention,
    summarize_community_temporal,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def _window(
    *,
    asset_id: str = "btc",
    start_offset_hours: int,
    posts: int,
    sentiment: float,
    sources: tuple[str, ...],
    narratives: tuple[tuple[str, int], ...],
) -> CommunityWindow:
    start = T0 + timedelta(hours=start_offset_hours)
    return CommunityWindow(
        asset_id=asset_id,
        window_start_utc=start,
        window_end_utc=start + timedelta(hours=1),
        posts_analyzed=posts,
        sentiment=sentiment,
        source_ids=sources,
        narratives=tuple(
            NarrativeMention(term=term, mentions=count)
            for term, count in narratives
        ),
        research_only=True,
        trade_influence_enabled=False,
    )


def test_temporal_summary_computes_raw_baseline_features() -> None:
    baseline = (
        _window(
            start_offset_hours=0,
            posts=10,
            sentiment=10.0,
            sources=("reddit-a",),
            narratives=(("ai", 2), ("risk", 4), ("old", 5)),
        ),
        _window(
            start_offset_hours=1,
            posts=20,
            sentiment=20.0,
            sources=("reddit-b",),
            narratives=(("ai", 4), ("risk", 2), ("old", 5)),
        ),
    )
    current = _window(
        start_offset_hours=3,
        posts=30,
        sentiment=30.0,
        sources=("reddit-a", "official-a"),
        narratives=(("ai", 5), ("risk", 3), ("old", 1), ("new", 2)),
    )

    summary = summarize_community_temporal(current, baseline)
    trends = {row.term: row for row in summary.narrative_trends}

    assert summary.baseline_window_count == 2
    assert summary.baseline_mean_sentiment == 15.0
    assert summary.sentiment_velocity == 15.0
    assert summary.discussion_volume_ratio == 2.0
    assert summary.current_source_diversity == 2
    assert summary.baseline_source_diversity == 2
    assert trends["ai"].baseline_mean_mentions == 3.0
    assert trends["ai"].state == "growing"
    assert trends["risk"].state == "stable"
    assert trends["old"].state == "fading"
    assert trends["new"].state == "growing"
    assert summary.research_only is True
    assert summary.trade_influence_enabled is False


def test_zero_volume_baseline_does_not_invent_ratio() -> None:
    baseline = (
        _window(
            start_offset_hours=0,
            posts=0,
            sentiment=0.0,
            sources=(),
            narratives=(),
        ),
    )
    current = _window(
        start_offset_hours=2,
        posts=5,
        sentiment=5.0,
        sources=("reddit-a",),
        narratives=(("btc", 1),),
    )

    summary = summarize_community_temporal(current, baseline)
    assert summary.discussion_volume_ratio is None


def test_temporal_summary_rejects_mixed_asset_baseline() -> None:
    current = _window(
        start_offset_hours=3,
        posts=5,
        sentiment=5.0,
        sources=("reddit-a",),
        narratives=(),
    )
    baseline = (
        _window(
            asset_id="eth",
            start_offset_hours=0,
            posts=5,
            sentiment=5.0,
            sources=("reddit-a",),
            narratives=(),
        ),
    )

    with pytest.raises(ValueError, match="cannot mix assets"):
        summarize_community_temporal(current, baseline)


def test_temporal_summary_rejects_lookahead_baseline() -> None:
    current = _window(
        start_offset_hours=2,
        posts=5,
        sentiment=5.0,
        sources=("reddit-a",),
        narratives=(),
    )
    overlapping = (
        _window(
            start_offset_hours=1,
            posts=5,
            sentiment=5.0,
            sources=("reddit-a",),
            narratives=(),
        ),
        _window(
            start_offset_hours=2,
            posts=5,
            sentiment=5.0,
            sources=("reddit-a",),
            narratives=(),
        ),
    )

    with pytest.raises(ValueError, match="baseline cannot look ahead"):
        summarize_community_temporal(current, overlapping)


def test_temporal_summary_requires_nonempty_immutable_baseline() -> None:
    current = _window(
        start_offset_hours=2,
        posts=5,
        sentiment=5.0,
        sources=("reddit-a",),
        narratives=(),
    )

    with pytest.raises(ValueError, match="nonempty immutable tuple"):
        summarize_community_temporal(current, ())

    with pytest.raises(ValueError, match="nonempty immutable tuple"):
        summarize_community_temporal(current, [])


def test_community_window_preserves_research_only_boundary() -> None:
    with pytest.raises(ValueError, match="community window is research_only"):
        CommunityWindow(
            asset_id="btc",
            window_start_utc=T0,
            window_end_utc=T0 + timedelta(hours=1),
            posts_analyzed=1,
            sentiment=0.0,
            source_ids=("reddit-a",),
            narratives=(),
            research_only=False,
        )

    with pytest.raises(
        ValueError,
        match="community window cannot enable trade influence",
    ):
        CommunityWindow(
            asset_id="btc",
            window_start_utc=T0,
            window_end_utc=T0 + timedelta(hours=1),
            posts_analyzed=1,
            sentiment=0.0,
            source_ids=("reddit-a",),
            narratives=(),
            trade_influence_enabled=True,
        )
