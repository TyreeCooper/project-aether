"""Paper-only horizon routing between the trading clock and strategy engine."""
from __future__ import annotations

from dataclasses import dataclass

from app.clock import HorizonController
from app.horizons import TradingHorizon


@dataclass(frozen=True)
class StrategyRoute:
    strategy_id: str
    strategy_version: str
    horizon: TradingHorizon


ROUTES: dict[TradingHorizon, StrategyRoute] = {
    TradingHorizon.SCALP: StrategyRoute("trend_breakout", "v3", TradingHorizon.SCALP),
    TradingHorizon.INTRADAY: StrategyRoute("trend_breakout", "v3", TradingHorizon.INTRADAY),
    TradingHorizon.SWING: StrategyRoute("trend_breakout", "v3", TradingHorizon.SWING),
    TradingHorizon.POSITION: StrategyRoute("trend_breakout", "v3", TradingHorizon.POSITION),
}


class PaperStrategyRouter:
    """Release enabled paper routes at most once per completed horizon bar."""

    def __init__(self) -> None:
        self.clock = HorizonController()

    def due(self, closed_ts: int) -> tuple[StrategyRoute, ...]:
        return tuple(
            ROUTES[horizon]
            for horizon in self.clock.due(closed_ts)
            if horizon in ROUTES
        )
