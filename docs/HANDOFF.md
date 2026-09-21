# Aether desk log

## Board

- Open slice: **strategy-stack**. Not agreed done.
- Live: blocked.
- Head: `da50102` shared runtime time-stop.

## Locks

- open

---

## Thread

### ChatGPT — END 2026-09-21 05:56 EDT

CI pass after restoring parse_ohlc_closes. Cohort + PF in score_exits. Push: time_stop_due on runtime; do not invent live PF.

### Grok — START 2026-09-21 05:56 EDT

Working strategy-stack. Lock: `backend/app/paper_exec.py`

### Grok — END 2026-09-21 05:57 EDT

SHA: `da50102`
Lock left: **open**

CI diagnosis (no test weakened):
- Failed runs 193–194: `ImportError: cannot import name parse_ohlc_closes from app.venue` while collecting `tests/test_venue.py`.
- Cause: market/UI venue rewrite dropped the helper the test still imported.
- Fix already on tip: ChatGPT `e5c4bef` restored the parser. CI run 195 on that SHA: **success** (52 tests). I did not delete or loosen that test.

Placed:
- Runtime now calls shared `time_stop_due(held_minutes, gain_pct, cost_pct)` before the engine's duplicate wall-clock block. Actor `bot-v3-time_stop`.
- Replay already used the same helper on 1m bar count. Threshold is identical: 180 and gain < cost*1.25.

score_exits: ChatGPT already cohorted `bot-v3-` + PF. I did not rewrite learn.py this turn.
Not AGREE DONE. No invented live numbers.

**Push to ChatGPT:** Confirm `shared_time_stop` in paper_exec. After Azure has `da50102`, if `/api/v1/learn` is reachable paste strategy cohort closed / expectancy / PF only. Next place if still open: 30-day research workflow, not UI.

END / ready for ChatGPT


### ChatGPT — START 2026-09-21 06:02 EDT

Working strategy-stack. Lock: `backend/app/engine.py`, strategy research workflow, related tests

Continuing because the stack is not complete to the best of my ability. Scan found one high-confidence durability gap: Kraken OHLC only returns a bounded recent window, and seed_history currently clears restored history, so accumulated >720 bars can be lost on restart. I am fixing restart-safe history merging and then will revalidate CI/deploy and research execution path. Live stays blocked. No UI work.


### ChatGPT — END 2026-09-21 06:18 EDT

SHA: `a60d29a7624d936b7a9769d98fdf3cf7dc21a099` (current tip; restart-safe history commit `f6a6fd1`, diagnostics commit `8b08da8`)
Lock left: open

What I completed this turn:
- Fixed restart durability: seed_history now merges restored/persisted 1m bars with fresh Kraken OHLC instead of clearing accumulated history back to the exchange's bounded recent window.
- Added a regression test proving overlap replacement + older-history preservation.
- Made Strategy Research run automatically on relevant strategy/research changes, still manually dispatchable, with stale expensive research cancelled when a newer research commit lands.
- Ran the first real 30-day research workflow successfully and captured actual evidence.
- Corrected walk-forward to produce exactly the requested four folds instead of a tiny fifth remainder fold.
- Added gap samples and explicit valid_for_profitability_gate.
- Added candidate diagnostics with full-sample + OOS aggregate + exit-reason reporting.
- Added research-only longer-horizon candidates (3h/6h/12h/24h) and configurable replay time-stop limits. These are diagnostic only; nothing auto-promotes to runtime.
- Added one-pass gap refetch. Missing candles are never interpolated or invented.
- CI at current tip: PASS, 55 tests.
- Azure deploy at current tip: PASS.

Hard evidence from the completed 30-day champion run:
- Data: 42,657 1m bars, one unresolved gap -> not valid for the final profitability gate.
- Champion full sample: 2 trades, 0 wins, net -$29.8108, PF 0.0, expectancy -$12.8923.
- Corrected OOS direction is also negative: no positive fold; observed OOS trades were losses. This is enough to reject any profitability claim for the current 5m/3h configuration.
- Therefore strategy-stack is NOT complete and I do not AGREE DONE.

Current research:
- Run `35587730755` is actively testing the pre-declared longer-horizon family under the same 0.80%/side conservative fee and 5bps slip assumptions. CI and Azure are already green for that code.
- Do not select a longer horizon until this run produces real OOS PF/expectancy/trade-count evidence.

Push to Grok: treat this END as your trigger. Inspect research run `35587730755` when complete. Report each candidate's OOS trades, net P/L, expectancy, PF, profitable folds, and data-quality gap status. If every candidate fails, diagnose the structural reason (fees/horizon/entry/exit) before changing runtime. If one candidate is positive, challenge it for sample size/overfit before proposing any champion change. No UI and no live.


### ChatGPT — START 2026-09-21 13:12 EDT

User explicitly expanded the active product scope to the Aether Intelligence layer. Lock: `backend/app/intelligence.py`, `backend/app/pair_book.py`, `backend/app/venue.py`, `backend/app/desk.py`, `backend/app/main.py`, intelligence UI/tests.

Building the first production intelligence tranche without changing live-trading safety: Kraken-native 24h opportunity metrics, per-asset MFE/MAE/capture analytics, cross-asset relative-strength/correlation context, source/risk-calendar scaffolding, and Floor/asset intelligence surfaces. Community/news/macro feeds remain evidence inputs, never direct buy/sell commands. Live stays blocked.
