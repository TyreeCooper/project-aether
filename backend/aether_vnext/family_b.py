"""Deterministic Family-B failed-break runtime for AETHER v1.4.

Family B is evaluated only after Family A is false on the same closed trigger bar.
The caller supplies the playbook-specific point-in-time counter-trend predicate and
whether the later closed bar has returned through the frozen failed-break level.
This module does not invert an open loser and does not size Risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from aether_vnext.playbook_runtime import family_regime_eligible
from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec


FAIL_WINDOWS: Final = MappingProxyType(
    {
        "pb_crypto_failed_break_v1_3": 12,
        "pb_eth_failed_break_v1_3": 12,
        "pb_fx_failed_session_v1_3": 4,
        "pb_fx_failed_swing_v1_3": 8,
        "pb_idx_failed_v1_3": 3,
        "pb_metal_failed_v1_3": 4,
        "pb_energy_failed_v1_3": 4,
        "pb_rates_failed_v1_3": 8,
        "pb_eq_failed_v1_3": 3,
    }
)


@dataclass(frozen=True, slots=True)
class FamilyBContext:
    break_printed: bool
    bars_since_break: int
    close_back_inside: bool
    counter_trend_condition: bool
    volatility_percentile: float
    position_key_open: bool = False
    locate_ok: bool | None = None

    def __post_init__(self) -> None:
        if int(self.bars_since_break) < 0:
            raise ValueError("bars_since_break cannot be negative")


@dataclass(frozen=True, slots=True)
class FamilyBEvaluation:
    playbook_id: str
    asset_id: str
    side: str
    definition_enabled: bool
    regime_eligible: bool
    fail_window_bars: int
    within_fail_window: bool
    silent_existing_open: bool
    structure_rule: bool
    locate_ok: bool

    @property
    def watch_eligible(self) -> bool:
        return (
            self.definition_enabled
            and self.regime_eligible
            and self.within_fail_window
            and not self.silent_existing_open
            and self.structure_rule
            and self.locate_ok
        )


def fail_window_bars(spec: PlaybookSpec) -> int:
    if spec.family is not PlaybookFamily.B:
        raise ValueError("fail_window_bars requires a Family-B playbook")
    try:
        return int(FAIL_WINDOWS[spec.playbook_id])
    except KeyError as exc:
        raise ValueError(
            f"Family-B playbook has no frozen fail window: {spec.playbook_id}"
        ) from exc


def evaluate_family_b_failure(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
    context: FamilyBContext,
) -> FamilyBEvaluation:
    if spec.family is not PlaybookFamily.B:
        raise ValueError("Family-B evaluator requires a Family-B playbook")
    if asset_id not in spec.allowed_assets:
        raise ValueError(f"asset {asset_id!r} not allowed by {spec.playbook_id}")
    if side not in spec.allowed_sides:
        raise ValueError(f"side {side!r} not allowed by {spec.playbook_id}")

    window = fail_window_bars(spec)
    within_window = 1 <= int(context.bars_since_break) <= window
    regime_eligible = family_regime_eligible(
        PlaybookFamily.B,
        volatility_percentile=context.volatility_percentile,
    )
    definition_enabled = spec.scout_definition_enabled

    locate_ok = True
    if spec.playbook_id == "pb_eq_failed_v1_3" and side == "short":
        locate_ok = context.locate_ok is True

    structure = bool(
        context.break_printed
        and within_window
        and context.close_back_inside
        and context.counter_trend_condition
        and regime_eligible
        and not context.position_key_open
    )

    return FamilyBEvaluation(
        playbook_id=spec.playbook_id,
        asset_id=asset_id,
        side=side,
        definition_enabled=definition_enabled,
        regime_eligible=regime_eligible,
        fail_window_bars=window,
        within_fail_window=within_window,
        silent_existing_open=bool(context.position_key_open),
        structure_rule=structure,
        locate_ok=locate_ok,
    )
