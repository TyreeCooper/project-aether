from app.db import summarize_fills


def test_summarize_fills_win_rate_and_duration():
    fills = [
        {
            "ts": "2026-09-20T20:00:00+00:00",
            "side": "buy",
            "qty_btc": 0.01,
            "fee_usd": 2.0,
            "realized_pnl_usd": 0,
        },
        {
            "ts": "2026-09-20T20:05:00+00:00",
            "side": "sell",
            "qty_btc": 0.01,
            "fee_usd": 2.0,
            "realized_pnl_usd": 5,
        },
        {
            "ts": "2026-09-20T20:10:00+00:00",
            "side": "buy",
            "qty_btc": 0.01,
            "fee_usd": 2.0,
            "realized_pnl_usd": 0,
        },
        {
            "ts": "2026-09-20T20:20:00+00:00",
            "side": "sell",
            "qty_btc": 0.01,
            "fee_usd": 2.0,
            "realized_pnl_usd": -3,
        },
    ]
    accounts = [{"equity": 9000, "peak_equity": 10000}]
    out = summarize_fills(fills, accounts)
    assert out["wins"] == 1
    assert out["losses"] == 1
    assert out["win_rate_pct"] == 50.0
    assert out["avg_trade_duration_seconds"] == 450.0
    assert out["fees_usd"] == 8.0
    assert out["max_drawdown_pct"] == 10.0
