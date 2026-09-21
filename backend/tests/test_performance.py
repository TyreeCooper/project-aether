from app.performance import summarize_backtest


def test_performance_summary_profit_factor_and_drawdown():
    trades = [
        {"pnl_usd": 10, "mae_pct": -0.5, "mfe_pct": 2.0},
        {"pnl_usd": -5, "mae_pct": -1.0, "mfe_pct": 0.4},
    ]
    curve = [
        {"ts": 1_700_000_000, "equity": 10_000},
        {"ts": 1_700_086_400, "equity": 10_010},
        {"ts": 1_700_172_800, "equity": 10_005},
    ]
    out = summarize_backtest(trades, curve, 10_000)
    assert out["profit_factor"] == 2.0
    assert out["payoff_ratio"] == 2.0
    assert out["net_pnl_usd"] == 5.0
    assert out["max_drawdown_pct"] > 0
