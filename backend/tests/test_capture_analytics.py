from datetime import datetime, timezone

from app.pair_book import PairBook
from app.paper_portfolio import PaperPortfolio


ASSET = {
    "id": "btc",
    "name": "Bitcoin",
    "symbol": "BTC",
    "pair": "BTC/USD",
    "kraken": "XBTUSD",
    "tv": "KRAKEN:XBTUSD",
}


def test_capture_analytics_separate_slippage_fees_and_exit_timing():
    wallet = PaperPortfolio(10_000)
    book = PairBook(ASSET, wallet)
    book.apply_quote({"last": 100.0, "bid": 99.9, "ask": 100.0})

    entry = book.enter(
        1_000,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "intraday",
            "risk_stop_pct": 2.0,
            "signal_key": "capture-test",
        },
        max_capital_usd=1_500,
    )
    assert entry["ok"] is True
    assert entry["reference_price"] == 100.0
    assert 4.9 < entry["slippage_bps"] < 5.1
    assert entry["slippage_usd"] > 0

    entered = datetime.fromisoformat(book.entry_at.replace("Z", "+00:00"))
    bucket = int(entered.timestamp()) // 60 * 60
    book.bars.clear()
    book.bars.append(
        {
            "ts": bucket,
            "open": 100.0,
            "high": 104.0,
            "low": 99.0,
            "close": 103.0,
            "volume": 1000,
        }
    )
    book.mark = 103.0
    book.bid = 102.9
    book.ask = 103.1
    book.highest = 104.0
    book.stop = 102.5

    closed = book.manage()
    assert closed is not None
    assert closed["ok"] is True
    assert closed["gross_return_pct"] > closed["net_return_pct"]
    assert closed["fees_usd"] > 0
    assert closed["slippage_usd"] > entry["slippage_usd"]
    assert closed["cost_drag_pct"] > 0
    assert closed["missed_opportunity_pct"] >= 0
    assert closed["net_missed_opportunity_pct"] >= closed["missed_opportunity_pct"]
    assert 0 <= closed["entry_efficiency_pct"] <= 100
    assert 0 <= closed["exit_efficiency_pct"] <= 100

    capture = book.capture_snapshot()
    assert capture["state"] == "last_closed"
    assert capture["net_capture_pct"] == closed["net_return_pct"]
    assert capture["fees_usd"] == closed["fees_usd"]
    assert capture["slippage_usd"] == closed["slippage_usd"]
