"""Deterministic Family-A structure evaluation for AETHER Playbook Pack v1.4.

The caller supplies point-in-time values derived from CLOSED bars and the correct
frozen reference for the playbook. This module evaluates only the Family-A setup
condition. It does not FIRE tickets, size risk, apply Clerk costs, or make
Governor decisions.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.playbook_runtime import family_regime_eligible
from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec


_LEVEL_TREND_PLAYBOOKS = frozenset(
    {
        "pb_fx_swing_v1_2",
        "pb_idx_scalp_v1_2",
        "pb_idx_intraday_v1_2",
        "pb_idx_swing_v1_2",
        "pb_metal_intraday_v1_2",
        "pb_metal_swing_v1_2",
        "pb_energy_intraday_v1_2",
        "pb_energy_swing_v1_2",
        "pb_rates_swing_v1_2",
        "pb_eq_scalp_v1_2",
        "pb_eq_intraday_v1_2",
        "pb_eq_swing_v1_2",
    }
)

_SLOPE_TREND_PLAYBOOKS = frozenset({"pb_fx_intraday_v1_2"})


@dataclass(frozen=True, slots=True)
class FamilyAContext:
    close: float
    volatility_percentile: float
    reference_high: float | None = None
    reference_low: float | None = None
    trend_ema20: float | None = None
    trend_ema50: float | None = None
    slope_ema20_current: float | None = None
    slope_ema20_previous: float | None = None
    btc_daily_close: float | None = None
    btc_daily_ema50: float | None = None
    btc_parent_watch_or_open_long: bool | None = None
    btc_parent_market_regime_eligible: bool | None = None

    def __post_init__(self) -> None:
        if float(self.close) <= 0:
            raise ValueError("close must be positive")


@dataclass(frozen=True, slots=True)
class FamilyAEvaluation:
    playbook_id: str
    asset_id: str
    side: str
    definition_enabled: bool
    regime_eligible: bool
    structure_rule: bool
    dependency_ok: bool

    @property
    def watch_eligible(self) -> bool:
        return (
            self.definition_enabled
            and self.regime_eligible
            and self.structure_rule
            and self.dependency_ok
        )


def _required(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"{name} is required")
    numeric = float(value)
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return numeric


def _breakout(
    *,
    side: str,
    close: float,
    reference_high: float | None,
    reference_low: float | None,
) -> bool:
    if side == "long":
        return float(close) > _required(reference_high, "reference_high")
    if side == "short":
        return float(close) < _required(reference_low, "reference_low")
    raise ValueError("side must be long or short")


def _ema_level_agrees(
    *,
    side: str,
    ema20: float | None,
    ema50: float | None,
) -> bool:
    fast = _required(ema20, "trend_ema20")
    slow = _required(ema50, "trend_ema50")
    if side == "long":
        return fast > slow
    if side == "short":
        return fast < slow
    raise ValueError("side must be long or short")


def _ema_slope_agrees(
    *,
    side: str,
    current: float | None,
    previous: float | None,
) -> bool:
    now = _required(current, "slope_ema20_current")
    prior = _required(previous, "slope_ema20_previous")
    if side == "long":
        return now > prior
    if side == "short":
        return now < prior
    raise ValueError("side must be long or short")


def evaluate_family_a_structure(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    context: FamilyAContext,
) -> FamilyAEvaluation:
    if spec.family is not PlaybookFamily.A:
        raise ValueError("Family-A evaluator requires a Family-A playbook")
    if asset_id not in spec.allowed_assets:
        raise ValueError(f"asset {asset_id!r} not allowed by {spec.playbook_id}")
    if side not in spec.allowed_sides:
        raise ValueError(f"side {side!r} not allowed by {spec.playbook_id}")

    definition_enabled = spec.scout_definition_enabled
    regime_eligible = family_regime_eligible(
        PlaybookFamily.A,
        volatility_percentile=context.volatility_percentile,
    )

    # BENCH definitions remain registered/queryable but Scout must not evaluate
    # them for tickets. Return without demanding unused structure inputs.
    if not definition_enabled:
        return FamilyAEvaluation(
            playbook_id=spec.playbook_id,
            asset_id=asset_id,
            side=side,
            definition_enabled=False,
            regime_eligible=regime_eligible,
            structure_rule=False,
            dependency_ok=True,
        )

    dependency_ok = True

    if spec.playbook_id == "pb_crypto_swing_v1_2":
        if side != "long":
            raise ValueError("crypto swing v1.2 is long-only")
        structure = (
            _breakout(
                side=side,
                close=context.close,
                reference_high=context.reference_high,
                reference_low=context.reference_low,
            )
            and _ema_level_agrees(
                side=side,
                ema20=context.trend_ema20,
                ema50=context.trend_ema50,
            )
            and _required(context.btc_daily_close, "btc_daily_close")
            > _required(context.btc_daily_ema50, "btc_daily_ema50")
        )

    elif spec.playbook_id == "pb_eth_rider_v1_2":
        if side != "long" or asset_id != "eth":
            raise ValueError("ETH rider is ETH long-only")
        structure = (
            _breakout(
                side=side,
                close=context.close,
                reference_high=context.reference_high,
                reference_low=context.reference_low,
            )
            and _ema_level_agrees(
                side=side,
                ema20=context.trend_ema20,
                ema50=context.trend_ema50,
            )
        )
        if context.btc_parent_watch_or_open_long is None:
            raise ValueError("btc_parent_watch_or_open_long is required")
        if context.btc_parent_market_regime_eligible is None:
            raise ValueError("btc_parent_market_regime_eligible is required")
        dependency_ok = bool(context.btc_parent_watch_or_open_long) and bool(
            context.btc_parent_market_regime_eligible
        )

    elif spec.playbook_id in _SLOPE_TREND_PLAYBOOKS:
        structure = (
            _breakout(
                side=side,
                close=context.close,
                reference_high=context.reference_high,
                reference_low=context.reference_low,
            )
            and _ema_slope_agrees(
                side=side,
                current=context.slope_ema20_current,
                previous=context.slope_ema20_previous,
            )
        )

    elif spec.playbook_id in _LEVEL_TREND_PLAYBOOKS:
        structure = (
            _breakout(
                side=side,
                close=context.close,
                reference_high=context.reference_high,
                reference_low=context.reference_low,
            )
            and _ema_level_agrees(
                side=side,
                ema20=context.trend_ema20,
                ema50=context.trend_ema50,
            )
        )

    else:
        raise ValueError(
            f"Family-A playbook has no frozen evaluator: {spec.playbook_id}"
        )

    return FamilyAEvaluation(
        playbook_id=spec.playbook_id,
        asset_id=asset_id,
        side=side,
        definition_enabled=definition_enabled,
        regime_eligible=regime_eligible,
        structure_rule=bool(structure and regime_eligible),
        dependency_ok=dependency_ok,
    )
