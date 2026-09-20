"""Market-data provider contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    source: str
    ts_ms: int | None = None


class MarketDataProvider(ABC):
    @abstractmethod
    async def get_mark(self, symbol: str) -> MarketSnapshot | None:
        """Return the latest market mark, or None when unavailable."""

    @abstractmethod
    async def get_seed_prices(self, symbol: str, limit: int = 120) -> list[float]:
        """Return recent prices used only to warm the paper strategy."""
