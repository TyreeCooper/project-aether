"""Historical replay adapter for the frozen Family A/B/C evaluators.

This module does not duplicate or reinterpret strategy rules. It only translates a
RegimeReadyReplayFeatures snapshot plus explicitly supplied unresolved PIT facts into
the existing Family evaluator context objects.

Any input whose source-bound timeframe/reference differs from the trigger-interval
snapshot remains explicit and caller-supplied. That includes higher-timeframe EMA
state, BTC daily dependencies, Family-B failed-break event state, equity locate state,
and equity Family-C nonconfirmation. The adapter never substitutes trigger-interval
EMA values for a higher-timeframe rule.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.family_a import (
    FamilyAContext,
    FamilyAEvaluation,
    evaluate_family_a_structure,
)
from aether_vnext.family_b import (
    FamilyBContext,
    FamilyBEvaluation,
    evaluate_family_b_failure,
)
from aether_vnext.family_c import (
    FamilyCContext,
    FamilyCEvaluation,
    evaluate_family_c_range,
)
from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec
from aether_vnext.replay_features import RegimeReadyReplayFeatures


@dataclass(frozen=True, slots=True)
class FamilyAReplayExtras:
    trend_ema20: float | None = None
    trend_ema50: float | None = None
    slope_ema20_current: float | None = None
    slope_ema20_previous: float | None = None
    btc_daily_close: float | None = None
    btc_daily_ema50: float | None = None
    btc_parent_watch_or_open_long: bool | None = None
    btc_parent_market_regime_eligible: bool | None = None


@dataclass(frozen=True, slots=True)
class FamilyBReplayState:
    break_printed: bool
    bars_since_break: int
    close_back_inside: bool
    counter_trend_condition: bool
    position_key_open: bool = False
    locate_ok: bool | None = None


@dataclass(frozen=True, slots=True)
class FamilyCReplayExtras:
    slope_ema20_current: float | None = None
    slope_ema20_previous: float | None = None
    trend_not_confirming: bool | None = None


def _validate_route_inputs(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    features: RegimeReadyReplayFeatures,
) -> None:
    if asset_id not in spec.allowed_assets:
        raise ValueError(f"asset {asset_id!r} not allowed by {spec.playbook_id}")
    if side not in spec.allowed_sides:
        raise ValueError(f"side {side!r} not allowed by {spec.playbook_id}")
    if features.numerical.asset_id != asset_id:
        raise ValueError("feature asset does not match replay route")
    if features.numerical.interval != spec.trigger_interval:
        raise ValueError("feature interval does not match playbook trigger interval")


def evaluate_replay_family_a(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    features: RegimeReadyReplayFeatures,
    extras: FamilyAReplayExtras | None = None,
) -> FamilyAEvaluation:
    if spec.family is not PlaybookFamily.A:
        raise ValueError("replay Family-A adapter requires a Family-A playbook")
    _validate_route_inputs(
        spec,
        asset_id=asset_id,
        side=side,
        features=features,
    )
    extra = extras or FamilyAReplayExtras()
    prior = features.numerical.prior_range

    context = FamilyAContext(
        close=features.numerical.close,
        volatility_percentile=features.volatility.percentile,
        reference_high=(None if prior is None else prior.high),
        reference_low=(None if prior is None else prior.low),
        trend_ema20=extra.trend_ema20,
        trend_ema50=extra.trend_ema50,
        slope_ema20_current=extra.slope_ema20_current,
        slope_ema20_previous=extra.slope_ema20_previous,
        btc_daily_close=extra.btc_daily_close,
        btc_daily_ema50=extra.btc_daily_ema50,
        btc_parent_watch_or_open_long=extra.btc_parent_watch_or_open_long,
        btc_parent_market_regime_eligible=(
            extra.btc_parent_market_regime_eligible
        ),
    )
    return evaluate_family_a_structure(
        spec,
        asset_id=asset_id,
        side=side,
        context=context,
    )


def evaluate_replay_family_b(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    features: RegimeReadyReplayFeatures,
    state: FamilyBReplayState,
) -> FamilyBEvaluation:
    if spec.family is not PlaybookFamily.B:
        raise ValueError("replay Family-B adapter requires a Family-B playbook")
    _validate_route_inputs(
        spec,
        asset_id=asset_id,
        side=side,
        features=features,
    )
    return evaluate_family_b_failure(
        spec,
        asset_id=asset_id,
        side=side,
        context=FamilyBContext(
            break_printed=state.break_printed,
            bars_since_break=state.bars_since_break,
            close_back_inside=state.close_back_inside,
            counter_trend_condition=state.counter_trend_condition,
            volatility_percentile=features.volatility.percentile,
            position_key_open=state.position_key_open,
            locate_ok=state.locate_ok,
        ),
    )


def evaluate_replay_family_c(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    features: RegimeReadyReplayFeatures,
    extras: FamilyCReplayExtras | None = None,
) -> FamilyCEvaluation:
    if spec.family is not PlaybookFamily.C:
        raise ValueError("replay Family-C adapter requires a Family-C playbook")
    _validate_route_inputs(
        spec,
        asset_id=asset_id,
        side=side,
        features=features,
    )
    prior = features.numerical.prior_range
    if prior is None:
        raise ValueError(
            "Family-C replay requires the playbook-correct prior range"
        )
    extra = extras or FamilyCReplayExtras()
    return evaluate_family_c_range(
        spec,
        asset_id=asset_id,
        side=side,
        context=FamilyCContext(
            close=features.numerical.close,
            volatility_percentile=features.volatility.percentile,
            prior_range_high=prior.high,
            prior_range_low=prior.low,
            slope_ema20_current=extra.slope_ema20_current,
            slope_ema20_previous=extra.slope_ema20_previous,
            trend_not_confirming=extra.trend_not_confirming,
        ),
    )
