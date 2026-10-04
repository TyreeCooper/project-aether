"""Deterministic Family-C range-harvest runtime for AETHER v1.4.

Family C is eligible only in the <40 realized-volatility percentile band and only
after Family A and B are false on the same closed trigger bar. This module owns
the source-bound range structure only; Clerk still owns the 1.25x cost hurdle.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.playbook_runtime import family_regime_eligible
from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec


@dataclass(frozen=True, slots=True)
class FamilyCContext:
    close: float
    volatility_percentile: float
    prior_range_high: float
    prior_range_low: float
    slope_ema20_current: float | None = None
    slope_ema20_previous: float | None = None
    trend_not_confirming: bool | None = None

    def __post_init__(self) -> None:
        if float(self.close) <= 0:
            raise ValueError("close must be positive")
        if float(self.prior_range_high) <= 0 or float(self.prior_range_low) <= 0:
            raise ValueError("prior range prices must be positive")
        if float(self.prior_range_high) <= float(self.prior_range_low):
            raise ValueError("prior_range_high must exceed prior_range_low")


@dataclass(frozen=True, slots=True)
class FamilyCEvaluation:
    playbook_id: str
    asset_id: str
    side: str
    definition_enabled: bool
    regime_eligible: bool
    outside_prior_range: bool
    trend_not_confirming: bool
    structure_rule: bool

    @property
    def watch_eligible(self) -> bool:
        return (
            self.definition_enabled
            and self.regime_eligible
            and self.outside_prior_range
            and self.trend_not_confirming
            and self.structure_rule
        )


def _fx_trend_not_confirming(
    *,
    side: str,
    current: float | None,
    previous: float | None,
) -> bool:
    if current is None or previous is None:
        raise ValueError(
            "FX range playbook requires slope_ema20_current and "
            "slope_ema20_previous"
        )
    now = float(current)
    prior = float(previous)
    if now <= 0 or prior <= 0:
        raise ValueError("EMA values must be positive")

    # Long range fade: breakout was down, so EMA must NOT be down.
    if side == "long":
        return now >= prior
    # Short range fade: breakout was up, so EMA must NOT be up.
    if side == "short":
        return now <= prior
    raise ValueError("side must be long or short")


def evaluate_family_c_range(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    context: FamilyCContext,
) -> FamilyCEvaluation:
    if spec.family is not PlaybookFamily.C:
        raise ValueError("Family-C evaluator requires a Family-C playbook")
    if asset_id not in spec.allowed_assets:
        raise ValueError(f"asset {asset_id!r} not allowed by {spec.playbook_id}")
    if side not in spec.allowed_sides:
        raise ValueError(f"side {side!r} not allowed by {spec.playbook_id}")

    regime_eligible = family_regime_eligible(
        PlaybookFamily.C,
        volatility_percentile=context.volatility_percentile,
    )

    if side == "long":
        outside = float(context.close) < float(context.prior_range_low)
    else:
        outside = float(context.close) > float(context.prior_range_high)

    if spec.playbook_id == "pb_fx_range_v1_3":
        trend_not_confirming = _fx_trend_not_confirming(
            side=side,
            current=context.slope_ema20_current,
            previous=context.slope_ema20_previous,
        )
    elif spec.playbook_id == "pb_eq_range_v1_3":
        if context.trend_not_confirming is None:
            raise ValueError(
                "equity range playbook requires explicit "
                "trend_not_confirming PIT input"
            )
        trend_not_confirming = bool(context.trend_not_confirming)
    else:
        raise ValueError(
            f"Family-C playbook has no frozen evaluator: {spec.playbook_id}"
        )

    structure = bool(
        regime_eligible
        and outside
        and trend_not_confirming
    )
    return FamilyCEvaluation(
        playbook_id=spec.playbook_id,
        asset_id=asset_id,
        side=side,
        definition_enabled=spec.scout_definition_enabled,
        regime_eligible=regime_eligible,
        outside_prior_range=outside,
        trend_not_confirming=trend_not_confirming,
        structure_rule=structure,
    )
