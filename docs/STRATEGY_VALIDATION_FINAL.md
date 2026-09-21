# Project Aether Strategy Validation — Final Round

## What is now implemented

The production paper strategy and the research stack are deliberately separate:

- Runtime: `sma_trend_breakout_v3` with completed 5m/15m bars, Donchian breakout,
  multi-horizon momentum, efficiency, volatility-regime filters, cost coverage,
  risk-capped sizing, cooldowns, structural/ATR stops, breakeven, and Chandelier trailing.
- Replay: uses a rolling 24-hour history window to match runtime memory and evaluates
  entries once per 5-minute bucket.
- Long-history research: public Binance.US `/api/v3/klines` pagination, local validation,
  baseline strategy comparison, and rolling out-of-sample folds.
- Benchmarks: buy-and-hold, SMA 8/21, EMA 12/26, Donchian 20/10, and Aether V3.
- Metrics: P/L, return, win rate, profit factor, payoff ratio, expectancy, MAE/MFE,
  max drawdown, and crypto-annualized daily Sharpe/Sortino.
- Research workflow: manual GitHub Action that downloads historical data and uploads a
  JSON report artifact. It does not modify production configuration or promote a model.

## Running the research workflow

GitHub -> Actions -> **Aether Strategy Research** -> **Run workflow**.

Default:
- 30 days
- BTCUSD
- 1-minute public Binance.US candles

The workflow produces `strategy-research.json`.

For a local run:

```bash
cd backend
PYTHONPATH=. python scripts/research_strategy.py --days 30 --symbol BTCUSD --output strategy-research.json
```

## Promotion rule

No candidate should be promoted because of one favorable backtest. At minimum require:

1. positive net expectancy after the configured taker fee, spread, and slippage;
2. acceptable drawdown;
3. more than one profitable out-of-sample fold;
4. enough closed trades to make the result interpretable;
5. performance that is not dominated by one isolated trade;
6. no runtime/replay rule mismatch.

Live trading remains blocked.
