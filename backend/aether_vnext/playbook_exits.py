"""Source-bound playbook exit geometry for AETHER vNext Phase 7.

This module preserves only exit facts explicitly bound by the Playbook Pack.
Where the source does not specify enough information to produce a unique hard
stop or deadline, the rule remains unresolved instead of inventing a value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Final

from aether_vnext.freeze import EvidenceState, US10Y_TICK_POINTS
from aether_vnext.playbooks import PLAYBOOK_REGISTRY, PlaybookFamily, PlaybookSpec


class StopAnchor(StrEnum):
    ENTRY = "entry"
    FROZEN_BREAKOUT = "frozen_breakout"
    PRIOR_RANGE_LOW = "prior_range_low"
    FAILED_EXTREME = "failed_extreme"
    UNBOUND = "unbound"


class TargetRule(StrEnum):
    NONE = "none"
    ENTRY_ONE_ATR = "entry_one_atr"
    RANGE_MIDPOINT = "range_midpoint"


class InvalidationRule(StrEnum):
    NONE = "none"
    FROZEN_BREAKOUT = "frozen_breakout"


@dataclass(frozen=True, slots=True)
class PlaybookExitRule:
    playbook_id: str
    stop_anchor: StopAnchor
    atr_multiplier: float
    time_stop: timedelta | None
    target_rule: TargetRule
    invalidation_rule: InvalidationRule
    stop_tick_size: float | None = None
    unresolved_reason: str | None = None

    @property
    def source_complete(self) -> bool:
        return self.unresolved_reason is None


@dataclass(frozen=True, slots=True)
class ExitGeometry:
    playbook_id: str
    side: str
    hard_stop_price: float | None
    structure_invalidation_level: float | None
    first_target_price: float | None
    time_stop_deadline_utc: datetime | None
    source_complete: bool
    unresolved_reason: str | None


def _td_minutes(minutes: int) -> timedelta:
    return timedelta(minutes=minutes)


def _td_hours(hours: int) -> timedelta:
    return timedelta(hours=hours)


def _td_days(days: int) -> timedelta:
    return timedelta(days=days)


_RULES: Final = {
    # Family A
    "pb_crypto_swing_v1_2": PlaybookExitRule(
        "pb_crypto_swing_v1_2",
        StopAnchor.PRIOR_RANGE_LOW,
        0.2,
        _td_days(5),
        TargetRule.ENTRY_ONE_ATR,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_eth_rider_v1_2": PlaybookExitRule(
        "pb_eth_rider_v1_2",
        StopAnchor.PRIOR_RANGE_LOW,
        0.2,
        None,
        TargetRule.NONE,
        InvalidationRule.NONE,
        unresolved_reason=(
            "source binds crypto-swing stop construction but does not bind "
            "rider time-stop, target, or structure-invalidation fields"
        ),
    ),
    "pb_fx_intraday_v1_2": PlaybookExitRule(
        "pb_fx_intraday_v1_2",
        StopAnchor.FROZEN_BREAKOUT,
        1.5,
        _td_minutes(180),
        TargetRule.ENTRY_ONE_ATR,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_fx_swing_v1_2": PlaybookExitRule(
        "pb_fx_swing_v1_2",
        StopAnchor.ENTRY,
        1.5,
        _td_days(5),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_idx_scalp_v1_2": PlaybookExitRule(
        "pb_idx_scalp_v1_2",
        StopAnchor.ENTRY,
        1.2,
        _td_minutes(45),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_idx_intraday_v1_2": PlaybookExitRule(
        "pb_idx_intraday_v1_2",
        StopAnchor.ENTRY,
        1.2,
        _td_minutes(180),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_idx_swing_v1_2": PlaybookExitRule(
        "pb_idx_swing_v1_2",
        StopAnchor.ENTRY,
        1.2,
        _td_days(5),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_metal_intraday_v1_2": PlaybookExitRule(
        "pb_metal_intraday_v1_2",
        StopAnchor.ENTRY,
        1.5,
        _td_minutes(180),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_metal_swing_v1_2": PlaybookExitRule(
        "pb_metal_swing_v1_2",
        StopAnchor.ENTRY,
        1.5,
        _td_days(5),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_energy_intraday_v1_2": PlaybookExitRule(
        "pb_energy_intraday_v1_2",
        StopAnchor.ENTRY,
        1.5,
        _td_minutes(180),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_energy_swing_v1_2": PlaybookExitRule(
        "pb_energy_swing_v1_2",
        StopAnchor.ENTRY,
        1.5,
        _td_days(5),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_rates_swing_v1_2": PlaybookExitRule(
        "pb_rates_swing_v1_2",
        StopAnchor.ENTRY,
        1.5,
        _td_days(5),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
        stop_tick_size=US10Y_TICK_POINTS,
    ),
    "pb_eq_scalp_v1_2": PlaybookExitRule(
        "pb_eq_scalp_v1_2",
        StopAnchor.ENTRY,
        1.2,
        _td_minutes(45),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_eq_intraday_v1_2": PlaybookExitRule(
        "pb_eq_intraday_v1_2",
        StopAnchor.ENTRY,
        1.2,
        _td_minutes(180),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),
    "pb_eq_swing_v1_2": PlaybookExitRule(
        "pb_eq_swing_v1_2",
        StopAnchor.ENTRY,
        1.2,
        _td_days(5),
        TargetRule.NONE,
        InvalidationRule.FROZEN_BREAKOUT,
    ),

    # Family B shared geometry: stop beyond failed extreme.
    "pb_crypto_failed_break_v1_3": PlaybookExitRule(
        "pb_crypto_failed_break_v1_3",
        StopAnchor.FAILED_EXTREME,
        0.2,
        _td_hours(24),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_eth_failed_break_v1_3": PlaybookExitRule(
        "pb_eth_failed_break_v1_3",
        StopAnchor.FAILED_EXTREME,
        0.2,
        _td_hours(24),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_fx_failed_session_v1_3": PlaybookExitRule(
        "pb_fx_failed_session_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_minutes(180),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_fx_failed_swing_v1_3": PlaybookExitRule(
        "pb_fx_failed_swing_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_days(5),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_idx_failed_v1_3": PlaybookExitRule(
        "pb_idx_failed_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_minutes(180),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_metal_failed_v1_3": PlaybookExitRule(
        "pb_metal_failed_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_minutes(180),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_energy_failed_v1_3": PlaybookExitRule(
        "pb_energy_failed_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_minutes(180),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),
    "pb_rates_failed_v1_3": PlaybookExitRule(
        "pb_rates_failed_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_days(5),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
        stop_tick_size=US10Y_TICK_POINTS,
    ),
    "pb_eq_failed_v1_3": PlaybookExitRule(
        "pb_eq_failed_v1_3",
        StopAnchor.FAILED_EXTREME,
        1.2,
        _td_minutes(180),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
    ),

    # Family C specifies a 1.0x ATR stop distance but no anchor. Preserve that
    # gap rather than silently assuming entry +/- ATR.
    "pb_fx_range_v1_3": PlaybookExitRule(
        "pb_fx_range_v1_3",
        StopAnchor.UNBOUND,
        1.0,
        _td_minutes(90),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
        unresolved_reason="Family-C 1.0x ATR stop anchor is not source-bound",
    ),
    "pb_eq_range_v1_3": PlaybookExitRule(
        "pb_eq_range_v1_3",
        StopAnchor.UNBOUND,
        1.0,
        _td_minutes(90),
        TargetRule.RANGE_MIDPOINT,
        InvalidationRule.NONE,
        unresolved_reason="Family-C 1.0x ATR stop anchor is not source-bound",
    ),
}

PLAYBOOK_EXIT_RULES: Final = MappingProxyType(_RULES)


def exit_rule(playbook_id: str) -> PlaybookExitRule:
    try:
        return PLAYBOOK_EXIT_RULES[str(playbook_id)]
    except KeyError as exc:
        raise KeyError(f"no executable exit rule for playbook: {playbook_id}") from exc


def _positive(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"{name} is required")
    numeric = float(value)
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return numeric


def _away_tick(price: float, *, side: str, tick_size: float | None) -> float:
    if tick_size is None:
        return float(price)
    tick = _positive(tick_size, "tick_size")
    ratio = float(price) / tick
    if side == "long":
        return math.floor(ratio + 1e-12) * tick
    if side == "short":
        return math.ceil(ratio - 1e-12) * tick
    raise ValueError("side must be long or short")


def build_exit_geometry(
    spec: PlaybookSpec,
    *,
    side: str,
    entry_price: float,
    atr: float,
    filled_at_utc: datetime,
    frozen_breakout_level: float | None = None,
    prior_range_low: float | None = None,
    failed_extreme: float | None = None,
    range_midpoint: float | None = None,
) -> ExitGeometry:
    if filled_at_utc.tzinfo is None:
        raise ValueError("filled_at_utc must be timezone-aware")
    if spec.evidence_state is EvidenceState.BENCH:
        raise ValueError("BENCH playbook cannot materialize an ExitGeometry")
    if side not in spec.allowed_sides:
        raise ValueError(f"side {side!r} not allowed by {spec.playbook_id}")

    rule = exit_rule(spec.playbook_id)
    entry = _positive(entry_price, "entry_price")
    atr_value = _positive(atr, "atr")

    hard_stop: float | None
    if rule.stop_anchor is StopAnchor.ENTRY:
        raw = (
            entry - rule.atr_multiplier * atr_value
            if side == "long"
            else entry + rule.atr_multiplier * atr_value
        )
        hard_stop = _away_tick(raw, side=side, tick_size=rule.stop_tick_size)
    elif rule.stop_anchor is StopAnchor.FROZEN_BREAKOUT:
        level = _positive(frozen_breakout_level, "frozen_breakout_level")
        raw = (
            level - rule.atr_multiplier * atr_value
            if side == "long"
            else level + rule.atr_multiplier * atr_value
        )
        hard_stop = _away_tick(raw, side=side, tick_size=rule.stop_tick_size)
    elif rule.stop_anchor is StopAnchor.PRIOR_RANGE_LOW:
        if side != "long":
            raise ValueError("prior-range-low stop construction is long-only")
        low = _positive(prior_range_low, "prior_range_low")
        raw = low - rule.atr_multiplier * atr_value
        hard_stop = _away_tick(raw, side=side, tick_size=rule.stop_tick_size)
    elif rule.stop_anchor is StopAnchor.FAILED_EXTREME:
        extreme = _positive(failed_extreme, "failed_extreme")
        raw = (
            extreme - rule.atr_multiplier * atr_value
            if side == "long"
            else extreme + rule.atr_multiplier * atr_value
        )
        hard_stop = _away_tick(raw, side=side, tick_size=rule.stop_tick_size)
    elif rule.stop_anchor is StopAnchor.UNBOUND:
        hard_stop = None
    else:
        raise ValueError(f"unsupported stop anchor: {rule.stop_anchor}")

    invalidation = (
        _positive(frozen_breakout_level, "frozen_breakout_level")
        if rule.invalidation_rule is InvalidationRule.FROZEN_BREAKOUT
        else None
    )

    if rule.target_rule is TargetRule.ENTRY_ONE_ATR:
        target = entry + atr_value if side == "long" else entry - atr_value
    elif rule.target_rule is TargetRule.RANGE_MIDPOINT:
        target = _positive(range_midpoint, "range_midpoint")
    else:
        target = None

    deadline = (
        filled_at_utc + rule.time_stop
        if rule.time_stop is not None
        else None
    )

    return ExitGeometry(
        playbook_id=spec.playbook_id,
        side=side,
        hard_stop_price=hard_stop,
        structure_invalidation_level=invalidation,
        first_target_price=target,
        time_stop_deadline_utc=deadline,
        source_complete=rule.source_complete,
        unresolved_reason=rule.unresolved_reason,
    )


def source_complete_playbook_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            playbook_id
            for playbook_id, rule in PLAYBOOK_EXIT_RULES.items()
            if rule.source_complete
        )
    )


def unresolved_playbook_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            playbook_id
            for playbook_id, rule in PLAYBOOK_EXIT_RULES.items()
            if not rule.source_complete
        )
    )
