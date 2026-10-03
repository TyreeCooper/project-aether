"""Build source-bound playbook trend features from immutable PIT research bars.

This research path mirrors the approved trend requirements without using live
exchange-print timestamps. It consumes an already-selected PIT research-bar slice,
validates the source-bound interval, and reuses Indicator Convention v1.

It does not resample bars, invent timeframes, infer dependencies, select playbooks,
or create evidence.
"""
from __future__ import annotations

from datetime import timedelta

from aether_vnext.indicator_convention import ema20, ema50
from aether_vnext.playbook_trend_features import (
    PlaybookTrendFeatureSnapshot,
)
from aether_vnext.playbook_trend_requirements import (
    TrendRuleKind,
    trend_requirement,
)
from aether_vnext.playbooks import playbook
from aether_vnext.research_bar_selection import PITResearchBarSlice
from aether_vnext.research_replay_features import ResearchFeatureBar


def _feature_rows(
    selection: PITResearchBarSlice,
) -> tuple[ResearchFeatureBar, ...]:
    rows = tuple(
        ResearchFeatureBar(
            research_bar_id=row.research_bar_id,
            asset_id=row.asset_id,
            interval=timedelta(seconds=row.interval_seconds),
            bucket_open_utc=row.bucket_open_utc,
            bucket_close_utc=row.bucket_close_utc,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
            available_at_utc=row.available_at_utc,
            source_id=row.source_id,
        )
        for row in selection.rows
    )
    for row in rows:
        if row.asset_id != selection.asset_id:
            raise ValueError("research trend bar asset mismatch")
        if row.available_at_utc > selection.as_of_utc:
            raise ValueError(
                "unavailable research trend bar cannot enter replay"
            )
        if row.bucket_close_utc > selection.as_of_utc:
            raise ValueError("future research trend bar cannot enter replay")
    return rows


def build_research_playbook_trend_features(
    playbook_id: str,
    selection: PITResearchBarSlice,
) -> PlaybookTrendFeatureSnapshot:
    """Compute reviewed PIT trend facts for one executable Family-A playbook."""
    spec = playbook(playbook_id)
    requirement = trend_requirement(playbook_id)
    if selection.asset_id not in spec.allowed_assets:
        raise ValueError(
            f"asset {selection.asset_id!r} not allowed by {spec.playbook_id}"
        )

    required_seconds = int(requirement.interval.total_seconds())
    if selection.interval_seconds != required_seconds:
        raise ValueError(
            "PIT research trend interval does not match playbook requirement"
        )

    rows = _feature_rows(selection)
    minimum = (
        21
        if requirement.rule_kind is TrendRuleKind.EMA20_SLOPE
        else 50
    )
    if len(rows) < minimum:
        raise ValueError(
            f"at least {minimum} PIT research trend bars are required"
        )

    current = ema20(rows)
    if requirement.rule_kind is TrendRuleKind.EMA20_SLOPE:
        previous = ema20(rows[:-1])
        slow = None
    elif requirement.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL:
        previous = None
        slow = ema50(rows)
    else:
        raise ValueError("unsupported playbook trend rule")

    return PlaybookTrendFeatureSnapshot(
        playbook_id=spec.playbook_id,
        asset_id=selection.asset_id,
        interval=requirement.interval,
        as_of_utc=selection.as_of_utc,
        source_bar_count=len(rows),
        last_bar_close_utc=rows[-1].bucket_close_utc,
        rule_kind=requirement.rule_kind,
        ema20_current=current,
        ema20_previous=previous,
        ema50_current=slow,
    )
