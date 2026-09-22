"""Trading-horizon registry for Aether's multi-horizon paper research.

A horizon describes intended holding behavior. It does not authorize execution.
Live execution remains outside this module and blocked by the runtime boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradingHorizon(str, Enum):
    HFT = "hft"
    SCALP = "scalp"
    INTRADAY = "intraday"
    SWING = "swing"
    POSITION = "position"


class HorizonState(str, Enum):
    CANDIDATE = "candidate"
    INFRASTRUCTURE_GATED = "infrastructure_gated"


@dataclass(frozen=True)
class HorizonSpec:
    horizon: TradingHorizon
    min_hold_seconds: int
    max_hold_seconds: int | None
    state: HorizonState
    execution_enabled: bool
    reason: str


HORIZON_REGISTRY: dict[TradingHorizon, HorizonSpec] = {
    TradingHorizon.HFT: HorizonSpec(
        TradingHorizon.HFT, 0, 1, HorizonState.INFRASTRUCTURE_GATED, False,
        "requires_specialized_low_latency_infrastructure",
    ),
    TradingHorizon.SCALP: HorizonSpec(
        TradingHorizon.SCALP, 1, 15 * 60, HorizonState.CANDIDATE, True,
        "paper_candidate_only",
    ),
    TradingHorizon.INTRADAY: HorizonSpec(
        TradingHorizon.INTRADAY, 5 * 60, 24 * 60 * 60, HorizonState.CANDIDATE, True,
        "paper_candidate_only",
    ),
    TradingHorizon.SWING: HorizonSpec(
        TradingHorizon.SWING, 4 * 60 * 60, 21 * 24 * 60 * 60, HorizonState.CANDIDATE, True,
        "paper_candidate_only",
    ),
    TradingHorizon.POSITION: HorizonSpec(
        TradingHorizon.POSITION, 24 * 60 * 60, None, HorizonState.CANDIDATE, True,
        "paper_candidate_only",
    ),
}


def horizon_spec(horizon: TradingHorizon | str) -> HorizonSpec:
    key = horizon if isinstance(horizon, TradingHorizon) else TradingHorizon(str(horizon).lower())
    return HORIZON_REGISTRY[key]


def applicable_horizons(*, include_gated: bool = True) -> tuple[TradingHorizon, ...]:
    return tuple(
        horizon
        for horizon, spec in HORIZON_REGISTRY.items()
        if include_gated or spec.execution_enabled
    )
