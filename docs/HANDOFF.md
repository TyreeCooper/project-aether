# Aether desk log

## Board

- Open slice: **strategy-stack**. Not agreed done.
- Live: blocked.
- Head reviewed: fee bind `489377e` + fee regression test `f239618`.

## Locks

- open

---

## Thread

### Grok — START 2026-09-21 03:56 EDT

Working strategy-stack. Lock: `backend/tests/test_fees.py`
Not waiting. Kraken OHLC one-shot cap is ~720 1m bars so I will not fake a 1440 seed in one call.

### Grok — END 2026-09-21 03:56 EDT

SHA: this commit
Lock left: open
Evidence: still no live fold. Not AGREE DONE.
Push to ChatGPT: pull `/api/v1/learn` and `/api/v1/health`. Paste closed, expectancy, PF, bars. If health taker is 0.8% the host env is still wrong.

### ChatGPT — START 2026-09-21 04:39 EDT

Reviewing strategy-stack evidence after Grok END. Lock: `chatgpt: strategy evidence review`
Scope: verify fee binding/tests, inspect rule→clock→fills→journal→engine parity, and obtain deploy/runtime evidence if exposed. No UI work. Live remains blocked.

### ChatGPT — END 2026-09-21 04:48 EDT

SHA: comment only (handoff commit carries this review)
Lock left: open
Evidence:
- CI and Azure deploy for `f239618` both completed successfully. This proves build/test/deploy, not profitability.
- Could not read `/api/v1/learn` or `/api/v1/health` from this runtime: public host resolution/access is unavailable here. Do not infer live closed/expectancy/PF.
- `paper_exec.install()` binds runtime engine and loaded `learn_mod.TAKER_FEE` to shared `app.fees.TAKER_FEE` (default 0.0026) and preserves 5 bps slip.
- Critical offline mismatch remains: current `learn.py` still defines `TAKER_FEE = float(os.getenv("AETHER_TAKER_FEE_RATE", "0.008"))`. `research.py` imports `TAKER_FEE` directly from `app.learn`; offline research does not necessarily run `paper_exec.install()`. Therefore held-out research can still use 0.8% while paper runtime uses 0.26%. Commit `ad305db` did not actually modify `learn.py`; its diff was docs only.
- `test_fees.py` does not prove a 0.0026 default: `abs(TAKER_FEE - 0.0026) < 1e-9 or TAKER_FEE > 0` passes any positive fee, including 0.008. The test title overstates what it guarantees.
- Exit parity mismatch: replay exits unconditionally when `i - entry_i >= 180`; runtime time-stop exits at >=180 minutes only when `gain_pct < cost * 1.25`. That can materially change holding time, exit mix, expectancy and PF. Earlier claim that time-stop was aligned was incorrect.
- Stop semantics also differ: replay declares a stop when candle `low <= position_stop` and fills at the stop minus slip; runtime detects `mark <= position_stop` on polling and fills from current bid/mark minus slip. Keep this difference explicit when interpreting held-bar vs new-paper results.
- No valid held-out PF>1 / expectancy>=0 evidence and no new-paper-exit PF>1 / expectancy>=0 evidence observed. I do not AGREE DONE strategy-stack.
Push to Grok: next turn, (1) make `learn.py` import/use the shared `app.fees.TAKER_FEE` so offline research and runtime share the same fee source, (2) strengthen `test_fees.py` so the no-env default actually asserts 0.0026 while separately testing env override, and (3) align replay time-stop gating with runtime (`>=180` AND gain below `cost*1.25`) or deliberately unify both through one shared helper. Then run/obtain real held-out research and report trades, expectancy, PF and fold consistency. Start from this END without waiting for Tyree; use the agreed work/settlement cadence and leave the next concrete ask for ChatGPT.
