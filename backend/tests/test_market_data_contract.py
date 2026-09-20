from app.market_data.base import MarketDataProvider, MarketSnapshot


class FakeMarketData(MarketDataProvider):
    async def get_mark(self, symbol: str) -> MarketSnapshot | None:
        return MarketSnapshot(symbol=symbol, price=50_000.0, source="fake")

    async def get_seed_prices(self, symbol: str, limit: int = 120) -> list[float]:
        return [49_000.0, 49_500.0, 50_000.0][-limit:]


def test_market_snapshot_contract():
    snap = MarketSnapshot(symbol="BTC/USD", price=50_000.0, source="fake")
    assert snap.symbol == "BTC/USD"
    assert snap.price == 50_000.0
    assert snap.source == "fake"
