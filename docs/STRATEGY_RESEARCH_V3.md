# Project Aether Strategy Research — V3

Date: 2026-09-21

## Objective

Improve the paper strategy without manufacturing profitability. The design goal is positive
out-of-sample expectancy after realistic fees, spread, slippage, and drawdowns. Live execution
remains blocked.

## Evidence used

1. Hurst, Ooi & Pedersen, "A Century of Evidence on Trend-Following Investing":
   https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing
   - Long-run evidence supports trend following / time-series momentum as a broad phenomenon.
   - This does not establish that a specific intraday BTC parameter set is profitable.

2. Gerritsen et al., "The profitability of technical trading rules in the Bitcoin market":
   https://doi.org/10.1016/j.frl.2019.08.011
   - Trading-range breakout rules showed forecasting power in their Bitcoin sample,
     particularly in strongly trending periods.

3. "Technical analysis in cryptocurrency markets: Do transaction costs and bubbles matter?":
   https://doi.org/10.1016/j.intfin.2022.101601
   - Moving-average and breakout profitability changes materially after transaction costs.
   - Aether therefore treats trading friction as a first-class entry condition.

4. Borgards, "Dynamic time series momentum of cryptocurrencies":
   https://doi.org/10.1016/j.najef.2021.101428
   - Reports momentum behavior at interday and intraday horizons, supporting confirmation
     across more than one lookback rather than a single SMA cross.

5. Moreira & Muir, "Volatility Managed Portfolios":
   https://www.nber.org/papers/w22208
   - Provides broad evidence that varying risk with volatility can improve risk-adjusted
     outcomes in other asset classes. Aether uses this conservatively as a position-size cap,
     not as a claim that the same result must hold for Bitcoin.

6. Han, Kang & Ryu, "Momentum in the Cryptocurrency Market: A Comprehensive Analysis under
   Realistic Assumptions":
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565
   - Emphasizes fat tails, realistic assumptions, and the distinction between statistical
     mean returns and actual profitability.

7. Bailey & López de Prado, "The Deflated Sharpe Ratio":
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
   - Strategy selection across many parameter combinations can inflate apparent backtest
     performance. Aether therefore keeps the candidate set small and requires more OOS trades.

8. Kraken Pro spot fee schedule:
   https://www.kraken.com/features/fee-schedule
   - As of this review, Tier-1 spot taker fees are 0.80% per execution. Aether's previous
     0.26% default understated a conservative taker/taker round trip.
   - Runtime now defaults to 0.80% per side and allows an explicit environment override via
     AETHER_TAKER_FEE_RATE.

## Repo findings that required correction

- Higher-timeframe resampling admitted partial 5m/15m candles.
- The "closed 5m" trigger fired when a new 5m bucket began, while strategy resampling could
  still include the new partial bucket.
- The runtime breakout horizon was changed by a monkey patch in paper_exec.py rather than
  being canonical in engine.py.
- Runtime had a weak-close filter that replay did not share.
- Replay did not mirror the two-loss re-entry gate or monotonic live trailing stop.
- The cost hurdle called historical range "opportunity", which was too easy to misread as a
  forecast of future price movement.
- Paper fee assumptions were stale relative to the current Kraken fee schedule.
- Position size was fixed even when stop distance and transaction friction changed.
- A single trend measure could qualify an entry without independent momentum confirmation.
- Marginal Donchian breaks and exhaustion bars were not distinguished.

## V3 design

Entry requires independent agreement from:
- completed 15m trend,
- completed 5m trend,
- directional efficiency,
- 1h/3h/6h time-series momentum vote,
- ATR compression/expansion state,
- 20-bar 5m Donchian break,
- minimum breakout distance in ATR units,
- strong close location,
- non-exhaustion bar range,
- realized-range capacity sufficient to cover modeled round-trip friction.

Risk and exit changes:
- stop uses ATR plus recent swing structure,
- breakeven only after enough movement to cover meaningful friction,
- Chandelier-style trailing stop lets larger trends run,
- trend-failure exit requires confirmation instead of a one-tick crossover,
- position quantity can only be reduced by a stop+cost risk budget,
- replay now keeps the stop monotonic and mirrors the loss-streak gate.

## Important limitation

The Kraken OHLC endpoint and current runtime store do not provide a sufficiently long research
history to establish profitability. V3 is a better-specified paper strategy, not proof of an
edge. Promotion decisions should eventually use months/years of clean historical bars,
multiple non-overlapping out-of-sample windows, and realistic execution assumptions.
