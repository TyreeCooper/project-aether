"""CoinGecko public-price provider used by paper mode only."""

from __future__ import annotations

import httpx

from app.market_data.base import MarketDataProvider, MarketSnapshot


class CoinGeckoMarketDataProvider(MarketDataProvider):
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.source = "coingecko"

    @staticmethod
    def _asset_id(symbol: str) -> tuple[str, str]:
        base, quote = symbol.upper().split("/")
        if base != "BTC" or quote != "USD":
            raise ValueError(f"CoinGecko paper provider only supports BTC/USD, got {symbol}")
        return "bitcoin", "usd"

    async def get_mark(self, symbol: str) -> MarketSnapshot | None:
        asset_id, quote = self._asset_id(symbol)
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": asset_id, "vs_currencies": quote}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            res = await client.get(url, params=params)
            res.raise_for_status()
            price = float(res.json()[asset_id][quote])
        return MarketSnapshot(symbol=symbol, price=price, source=self.source)

    async def get_seed_prices(self, symbol: str, limit: int = 120) -> list[float]:
        asset_id, quote = self._asset_id(symbol)
        url = f"https://api.coingecko.com/api/v3/coins/{asset_id}/market_chart"
        params = {"vs_currency": quote, "days": "1"}
        async with httpx.AsyncClient(timeout=max(self.timeout_seconds, 15.0)) as client:
            res = await client.get(url, params=params)
            res.raise_for_status()
            prices = res.json().get("prices") or []
        return [float(px) for _ts, px in prices[-limit:]]
