"""Temporal community-intelligence research for AETHER vNext.

This layer computes descriptive rolling-baseline features only. It does not
classify trade direction, create orders, or bind promotion thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


NARRATIVE_STATES = frozenset({"growing", "stable", "fading"})


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class NarrativeMention:
    term: str
    mentions: int

    def __post_init__(self) -> None:
        _canonical_text("term", self.term)
        if (
            not isinstance(self.mentions, int)
            or isinstance(self.mentions, bool)
            or self.mentions < 0
        ):
            raise ValueError("mentions must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class CommunityWindow:
    asset_id: str
    window_start_utc: datetime
    window_end_utc: datetime
    posts_analyzed: int
    sentiment: float
    source_ids: tuple[str, ...]
    narratives: tuple[NarrativeMention, ...]
    research_only: bool = True
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        _canonical_text("asset_id", self.asset_id)
        if self.asset_id != self.asset_id.lower():
            raise ValueError("asset_id must be canonical lowercase")
        for name in ("window_start_utc", "window_end_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.window_end_utc <= self.window_start_utc:
            raise ValueError("community window must have positive duration")
        if (
            not isinstance(self.posts_analyzed, int)
            or isinstance(self.posts_analyzed, bool)
            or self.posts_analyzed < 0
        ):
            raise ValueError("posts_analyzed must be a nonnegative integer")
        if isinstance(self.sentiment, bool) or not math.isfinite(
            float(self.sentiment)
        ):
            raise ValueError("sentiment must be finite numeric")
        if not -100.0 <= float(self.sentiment) <= 100.0:
            raise ValueError("sentiment must be in [-100,100]")
        if not isinstance(self.source_ids, tuple):
            raise ValueError("source_ids must be an immutable tuple")
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            for value in self.source_ids
        ):
            raise ValueError("source_ids entries must be canonical text")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if not isinstance(self.narratives, tuple):
            raise ValueError("narratives must be an immutable tuple")
        terms = tuple(row.term for row in self.narratives)
        if len(set(terms)) != len(terms):
            raise ValueError("narrative terms must be unique")
        if self.research_only is not True:
            raise ValueError("community window is research_only")
        if self.trade_influence_enabled is not False:
            raise ValueError("community window cannot enable trade influence")


@dataclass(frozen=True, slots=True)
class NarrativeTrend:
    term: str
    baseline_mean_mentions: float
    current_mentions: int
    state: str

    def __post_init__(self) -> None:
        _canonical_text("term", self.term)
        if self.state not in NARRATIVE_STATES:
            raise ValueError("invalid narrative state")
        if (
            not math.isfinite(float(self.baseline_mean_mentions))
            or self.baseline_mean_mentions < 0
        ):
            raise ValueError(
                "baseline_mean_mentions must be finite and nonnegative"
            )
        if (
            not isinstance(self.current_mentions, int)
            or isinstance(self.current_mentions, bool)
            or self.current_mentions < 0
        ):
            raise ValueError(
                "current_mentions must be a nonnegative integer"
            )


@dataclass(frozen=True, slots=True)
class CommunityTemporalSummary:
    asset_id: str
    baseline_window_count: int
    current_sentiment: float
    baseline_mean_sentiment: float
    sentiment_velocity: float
    discussion_volume_ratio: float | None
    current_source_diversity: int
    baseline_source_diversity: int
    narrative_trends: tuple[NarrativeTrend, ...]
    as_of_utc: datetime
    research_only: bool = True
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        _canonical_text("asset_id", self.asset_id)
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if (
            not isinstance(self.baseline_window_count, int)
            or isinstance(self.baseline_window_count, bool)
            or self.baseline_window_count <= 0
        ):
            raise ValueError("baseline_window_count must be positive")
        for name in (
            "current_sentiment",
            "baseline_mean_sentiment",
            "sentiment_velocity",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.discussion_volume_ratio is not None and (
            not math.isfinite(float(self.discussion_volume_ratio))
            or self.discussion_volume_ratio < 0
        ):
            raise ValueError(
                "discussion_volume_ratio must be finite and nonnegative"
            )
        for name in (
            "current_source_diversity",
            "baseline_source_diversity",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be nonnegative")
        if not isinstance(self.narrative_trends, tuple):
            raise ValueError("narrative_trends must be an immutable tuple")
        if self.research_only is not True:
            raise ValueError("community temporal summary is research_only")
        if self.trade_influence_enabled is not False:
            raise ValueError(
                "community temporal summary cannot enable trade influence"
            )


def summarize_community_temporal(
    current: CommunityWindow,
    baseline: tuple[CommunityWindow, ...],
) -> CommunityTemporalSummary:
    if not isinstance(baseline, tuple) or not baseline:
        raise ValueError("baseline must be a nonempty immutable tuple")
    if any(row.asset_id != current.asset_id for row in baseline):
        raise ValueError("community baseline cannot mix assets")
    if any(row.window_end_utc > current.window_start_utc for row in baseline):
        raise ValueError("community baseline cannot look ahead")

    baseline_sentiment = sum(
        float(row.sentiment) for row in baseline
    ) / len(baseline)
    baseline_posts = sum(row.posts_analyzed for row in baseline) / len(baseline)
    volume_ratio = (
        None
        if baseline_posts == 0
        else current.posts_analyzed / baseline_posts
    )

    baseline_sources = {
        source_id
        for row in baseline
        for source_id in row.source_ids
    }
    current_sources = set(current.source_ids)

    current_mentions = {
        row.term: row.mentions for row in current.narratives
    }
    baseline_totals: dict[str, int] = {}
    for window in baseline:
        for mention in window.narratives:
            baseline_totals[mention.term] = (
                baseline_totals.get(mention.term, 0) + mention.mentions
            )

    all_terms = sorted(set(current_mentions) | set(baseline_totals))
    trends: list[NarrativeTrend] = []
    for term in all_terms:
        baseline_mean = baseline_totals.get(term, 0) / len(baseline)
        current_count = current_mentions.get(term, 0)
        if current_count > baseline_mean:
            state = "growing"
        elif current_count < baseline_mean:
            state = "fading"
        else:
            state = "stable"
        trends.append(
            NarrativeTrend(
                term=term,
                baseline_mean_mentions=baseline_mean,
                current_mentions=current_count,
                state=state,
            )
        )

    return CommunityTemporalSummary(
        asset_id=current.asset_id,
        baseline_window_count=len(baseline),
        current_sentiment=float(current.sentiment),
        baseline_mean_sentiment=baseline_sentiment,
        sentiment_velocity=float(current.sentiment) - baseline_sentiment,
        discussion_volume_ratio=volume_ratio,
        current_source_diversity=len(current_sources),
        baseline_source_diversity=len(baseline_sources),
        narrative_trends=tuple(trends),
        as_of_utc=current.window_end_utc,
        research_only=True,
        trade_influence_enabled=False,
    )
