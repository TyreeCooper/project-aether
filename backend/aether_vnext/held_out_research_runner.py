"""Fail-closed preflight for the canonical HELD_OUT historical research runner.

The vNext playbooks require EMA, ATR, realized-volatility, and prior closed-bar range
inputs. Only the prior-range convention is currently source-bound. This module
exposes that fact before any research runner is allowed to manufacture a backtest.

It performs no database writes, no market I/O, and no trading actions.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether_vnext.forward_paper_preflight import (
    canonical_forward_paper_route_requests,
)
from aether_vnext.indicator_authority import indicator_authority_blockers
from aether_vnext.playbooks import playbook


REQUIRED_INDICATORS = (
    "ema",
    "atr",
    "realized_vol",
    "prior_closed_bar_range",
)


@dataclass(frozen=True, slots=True)
class HeldOutResearchRoutePlan:
    route_id: str
    playbook_id: str
    playbook_version: str
    mechanism_class: str


@dataclass(frozen=True, slots=True)
class HeldOutResearchRunnerPreflight:
    route_count: int
    routes: tuple[HeldOutResearchRoutePlan, ...]
    required_indicators: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def startable(self) -> bool:
        return not self.blockers


def canonical_held_out_research_plan(
) -> tuple[HeldOutResearchRoutePlan, ...]:
    """Return the exact no-cherry-pick executable research universe."""
    rows = []
    for request in canonical_forward_paper_route_requests():
        spec = playbook(request.playbook_id)
        rows.append(
            HeldOutResearchRoutePlan(
                route_id=request.route_id,
                playbook_id=request.playbook_id,
                playbook_version=spec.version,
                mechanism_class=spec.mechanism_class,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (row.route_id, row.playbook_id),
        )
    )


def preflight_canonical_held_out_research_runner(
) -> HeldOutResearchRunnerPreflight:
    """Refuse research execution until all required indicator math is bound."""
    routes = canonical_held_out_research_plan()
    blockers = indicator_authority_blockers(REQUIRED_INDICATORS)
    return HeldOutResearchRunnerPreflight(
        route_count=len(routes),
        routes=routes,
        required_indicators=REQUIRED_INDICATORS,
        blockers=blockers,
    )
