"""Shared deterministic runtime laws for AETHER Playbook Pack v1.4.

This module owns only source-bound mechanics shared across playbook families:
- closed-trigger clock binding from each playbook's explicit interval;
- volatility-band eligibility;
- Family A -> B -> C same-bar precedence;
- traceable evaluation-disposition vocabulary.

It does not implement Scout/Sniper seat transitions, Clerk cost decisions, Risk,
Governor, or execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aether_vnext.playbooks import PlaybookFamily, PlaybookSpec
from aether_vnext.trading_clock import RouteClockSpec


class EvaluationDisposition(StrEnum):
    NOT_DUE = "not_due"
    REGIME_BLOCK = "regime_block"
    STRUCTURE_FAIL = "structure_fail"
    DEPENDENCY_BLOCK = "dependency_block"
    COST_EDGE_FAIL = "cost_edge_fail"
    RISK_BLOCK = "risk_block"
    VENUE_BLOCK = "venue_block"
    TICKET_CREATED = "ticket_created"
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"


class VolatilityBand(StrEnum):
    BELOW_40 = "below_40"
    ELIGIBLE_40_85 = "eligible_40_85"
    ABOVE_85 = "above_85"


@dataclass(frozen=True, slots=True)
class FamilyPrecedenceDecision:
    selected_family: PlaybookFamily | None
    reason: str


def volatility_band(percentile: float) -> VolatilityBand:
    value = float(percentile)
    if value < 0.0 or value > 100.0:
        raise ValueError("volatility percentile must be in [0, 100]")
    if value < 40.0:
        return VolatilityBand.BELOW_40
    if value <= 85.0:
        return VolatilityBand.ELIGIBLE_40_85
    return VolatilityBand.ABOVE_85


def family_regime_eligible(
    family: PlaybookFamily,
    *,
    volatility_percentile: float,
) -> bool:
    """Apply the source-frozen family volatility bands.

    Families A/B use the shared mid-volatility gate [40,85], inclusive.
    Family C is range harvest and is eligible only below 40.
    """
    band = volatility_band(volatility_percentile)
    if family in {PlaybookFamily.A, PlaybookFamily.B}:
        return band is VolatilityBand.ELIGIBLE_40_85
    if family is PlaybookFamily.C:
        return band is VolatilityBand.BELOW_40
    raise ValueError(f"unsupported playbook family: {family}")


def resolve_family_precedence(
    *,
    family_a_structure_rule: bool,
    family_b_fail_event: bool,
    family_c_structure_rule: bool,
) -> FamilyPrecedenceDecision:
    """Resolve the binding same-bar A -> B -> C precedence.

    Inputs are the fully evaluated family predicates for the closed trigger bar,
    including each family's own trend/regime requirements.
    """
    if family_a_structure_rule:
        return FamilyPrecedenceDecision(
            selected_family=PlaybookFamily.A,
            reason="family_a_structure",
        )
    if family_b_fail_event:
        return FamilyPrecedenceDecision(
            selected_family=PlaybookFamily.B,
            reason="family_b_fail_event",
        )
    if family_c_structure_rule:
        return FamilyPrecedenceDecision(
            selected_family=PlaybookFamily.C,
            reason="family_c_structure",
        )
    return FamilyPrecedenceDecision(
        selected_family=None,
        reason=EvaluationDisposition.STRUCTURE_FAIL.value,
    )


def playbook_evaluation_key(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
) -> str:
    if asset_id not in spec.allowed_assets:
        raise ValueError(
            f"asset {asset_id!r} not allowed by {spec.playbook_id}"
        )
    if side not in spec.allowed_sides:
        raise ValueError(
            f"side {side!r} not allowed by {spec.playbook_id}"
        )
    return "|".join(
        (
            spec.playbook_id,
            asset_id,
            side,
            spec.horizon,
        )
    )


def clock_spec_for_playbook(
    spec: PlaybookSpec,
    *,
    asset_id: str,
    side: str,
) -> RouteClockSpec:
    """Bind TradingClock to the playbook's explicit trigger interval.

    route_key here is an evaluation identity, not the Portfolio position_key.
    Multiple playbooks may evaluate the same asset/side/horizon while the later
    Family-precedence law decides which setup may survive on a closed bar.
    """
    return RouteClockSpec(
        route_key=playbook_evaluation_key(
            spec,
            asset_id=asset_id,
            side=side,
        ),
        asset_id=asset_id,
        horizon=spec.horizon,
        trigger_interval=spec.trigger_interval,
        active=spec.scout_definition_enabled,
        supported=True,
    )
