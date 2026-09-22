from app.fill_model import fill_cost, round_trip_cost

def test_buy_crosses_ask_then_slips_adversely():
    fill = fill_cost("buy", 2, bid=99, ask=100, mark=99.5, fee_rate=0.01, slippage_bps=10)
    assert fill is not None
    assert fill.reference_price == 100
    assert fill.fill_price == 100.1
    assert fill.notional == 200.2
    assert abs(fill.fee - 2.002) < 1e-9
    assert abs(fill.slippage - 0.2) < 1e-9

def test_sell_crosses_bid_then_slips_adversely():
    fill = fill_cost("sell", 1, bid=100, ask=101, mark=100.5, fee_rate=0.0, slippage_bps=10)
    assert fill is not None and fill.fill_price == 99.9

def test_mark_is_only_quote_fallback():
    fill = fill_cost("buy", 1, bid=None, ask=None, mark=50, fee_rate=0, slippage_bps=0)
    assert fill is not None and fill.fill_price == 50
    assert fill_cost("buy", 1, bid=None, ask=None, mark=None, fee_rate=0, slippage_bps=0) is None

def test_invalid_side_or_quantity_does_not_fill():
    assert fill_cost("hold", 1, bid=1, ask=1, mark=1, fee_rate=0, slippage_bps=0) is None
    assert fill_cost("buy", 0, bid=1, ask=1, mark=1, fee_rate=0, slippage_bps=0) is None

def test_round_trip_includes_spread_fees_and_slippage():
    cost = round_trip_cost(1, bid=99, ask=101, fee_rate=0.01, slippage_bps=10)
    buy = fill_cost("buy", 1, bid=99, ask=101, mark=None, fee_rate=0.01, slippage_bps=10)
    sell = fill_cost("sell", 1, bid=99, ask=101, mark=None, fee_rate=0.01, slippage_bps=10)
    assert buy is not None and sell is not None
    assert abs(cost - (2 + buy.fee + sell.fee + buy.slippage + sell.slippage)) < 1e-9
