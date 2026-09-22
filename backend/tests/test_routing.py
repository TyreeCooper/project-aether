from app.horizons import TradingHorizon
from app.routing import PaperStrategyRouter, ROUTES


def test_router_releases_enabled_horizons_only():
    router = PaperStrategyRouter()
    due = router.due(3599)
    horizons = {route.horizon for route in due}
    assert TradingHorizon.HFT not in horizons
    assert TradingHorizon.SCALP in horizons
    assert TradingHorizon.INTRADAY in horizons
    assert TradingHorizon.SWING in horizons


def test_router_is_at_most_once_per_closed_bucket():
    router = PaperStrategyRouter()
    first = router.due(299)
    second = router.due(299)
    assert first
    assert second == ()


def test_routes_carry_stable_strategy_attribution():
    route = ROUTES[TradingHorizon.INTRADAY]
    assert route.strategy_id == "trend_breakout"
    assert route.strategy_version == "v3"
    assert route.horizon == TradingHorizon.INTRADAY
