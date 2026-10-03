"""Bind source-bound trend snapshots into Family-A replay inputs.

This module removes manual EMA field copying from historical replay while preserving
all unresolved dependency facts as explicit caller inputs.

It does not compute indicators, select bars, infer BTC parent state, select a
playbook, or create evidence.
"""
from __future__ import annotations

from aether_vnext.playbook_trend_features import (
    PlaybookTrendFeatureSnapshot,
)
from aether_vnext.playbook_trend_requirements import (
    TrendRuleKind,
    trend_requirement,
)
from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec
from aether_vnext.replay_family_adapter import FamilyAReplayExtras
from aether_vnext.replay_features import RegimeReadyReplayFeatures


def family_a_extras_from_trend_snapshot(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    features: RegimeReadyReplayFeatures,
    trend: PlaybookTrendFeatureSnapshot,
    btc_daily_close: float | None = None,
    btc_daily_ema50: float | None = None,
    btc_parent_watch_or_open_long: bool | None = None,
    btc_parent_market_regime_eligible: bool | None = None,
) -> FamilyAReplayExtras:
    """Translate reviewed PIT trend facts into the frozen Family-A input shape."""
    if spec.family is not PlaybookFamily.A:
        raise ValueError("trend replay adapter requires a Family-A playbook")
    asset = str(asset_id).strip().lower()
    if not asset:
        raise ValueError("asset_id is required")
    if asset not in spec.allowed_assets:
        raise ValueError(f"asset {asset!r} not allowed by {spec.playbook_id}")
    if features.numerical.asset_id != asset:
        raise ValueError("replay feature asset mismatch")
    if trend.playbook_id != spec.playbook_id:
        raise ValueError("trend snapshot playbook mismatch")
    if trend.asset_id != asset:
        raise ValueError("trend snapshot asset mismatch")

    requirement = trend_requirement(spec.playbook_id)
    if trend.interval != requirement.interval:
        raise ValueError("trend snapshot interval mismatch")
    if trend.rule_kind is not requirement.rule_kind:
        raise ValueError("trend snapshot rule mismatch")

    trigger_close = features.numerical.trigger_bar.bucket_close_utc
    if trend.last_bar_close_utc > trigger_close:
        raise ValueError("future trend bar cannot enter replay")
    if trend.as_of_utc > trigger_close:
        raise ValueError("future trend snapshot cannot enter replay")

    if requirement.rule_kind is TrendRuleKind.EMA20_SLOPE:
        if trend.ema20_previous is None:
            raise ValueError("EMA20 slope replay requires previous EMA20")
        if trend.ema50_current is not None:
            raise ValueError("EMA20 slope replay cannot carry EMA50 level state")
        trend_ema20 = None
        trend_ema50 = None
        slope_current = trend.ema20_current
        slope_previous = trend.ema20_previous
    elif requirement.rule_kind is TrendRuleKind.EMA20_EMA50_LEVEL:
        if trend.ema50_current is None:
            raise ValueError("EMA20/EMA50 replay requires EMA50")
        if trend.ema20_previous is not None:
            raise ValueError("EMA20/EMA50 replay cannot carry slope state")
        trend_ema20 = trend.ema20_current
        trend_ema50 = trend.ema50_current
        slope_current = None
        slope_previous = None
    else:
        raise ValueError("unsupported source-bound trend rule")

    return FamilyAReplayExtras(
        trend_ema20=trend_ema20,
        trend_ema50=trend_ema50,
        slope_ema20_current=slope_current,
        slope_ema20_previous=slope_previous,
        btc_daily_close=btc_daily_close,
        btc_daily_ema50=btc_daily_ema50,
        btc_parent_watch_or_open_long=btc_parent_watch_or_open_long,
        btc_parent_market_regime_eligible=btc_parent_market_regime_eligible,
    )
