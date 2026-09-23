# AETHER-LOAD-003 — Qualified Trade Throughput & Risk Architecture

## CONTROL STATUS

- Load: AETHER-LOAD-003
- State: CONTROL FILE ESTABLISHED
- Active implementation batch: NONE
- Waiting on: GROK BOT J.A.R.V.I.S. CLEARANCE TO START B1
- Starting main SHA: 09dfdb510bd5b54f43cef7e9c5f20389d3636ae1
- Live-money execution: HARD BLOCKED
- Paper testing: remains the target runtime
- Rule: ONE batch active at a time. Never advance without Grok clearance.

---

# Mission

Convert Aether from the temporary LOAD-002 forced execution experiment into the real ongoing paper STRATEGY TEST runtime.

Aether must:

1. continuously search every supported asset × horizon route;
2. require a real favorable setup before any strategy entry;
3. execute as many qualified paper trades as portfolio risk permits;
4. progressively remove weak/bad opportunities through gates;
5. preserve each trade's originating horizon from entry through exit;
6. size every trade with explicit instrument and portfolio risk limits;
7. model spread, fees, slippage, and realistic paper fills;
8. preserve isolated forced execution validation as a separate manual tool;
9. keep real-money/live broker execution hard blocked.

Core rule:

> Aether should always be searching for a trade, not always be in a trade. Trade count is an output of qualified opportunity and may never override setup quality or risk.

---

# Runtime state required when LOAD-003 is finished

## ACTIVE

- STRATEGY TEST / PAPER runtime
- Desk armed
- Continuous market scanning
- Every configured asset × horizon route evaluated on its proper completed-bar clock
- Genuine setup/trigger requirement
- Long paper execution where supported
- Short paper execution where supported
- Horizon-specific position identity
- Horizon-specific position management
- Per-trade risk sizing
- Aggregate portfolio open-risk control
- Asset/cluster exposure control
- FX lot conversion and explicit hard ceiling
- Micro-futures contract ceiling
- Realistic spread/fee/slippage accounting
- Live Trades / Blotter evidence
- Persistence/restart recovery

## OFF

- Global forced strategy entries
- Forced BUY behavior in the running strategy desk
- LOAD-002 execution experiment as the default runtime
- Arbitrary four-position count as the primary portfolio governor
- News/community/macro/crypto intelligence creating trades
- Live-money execution

## AVAILABLE BUT ISOLATED

- LOAD-002 execution validation
- Forced execution matrix
- Asset × horizon × direction execution plumbing tests
- Minimum-quantity execution checks

Execution validation must never be confused with strategy performance.

---

# Initial risk contract

These values are testing guardrails for LOAD-003. They may be revised later only with explicit evidence and a separate approved change.

- Maximum target risk per strategy trade: 0.75% of equity
- Maximum aggregate open stop-risk: 3.00% of equity
- FX maximum: 1.00 standard lot = 100,000 base-currency units per trade
- MES maximum: 1 contract per trade
- MNQ maximum: 1 contract per trade
- MGC maximum: 1 contract per trade
- MCL maximum: 1 contract per trade
- US10Y maximum: 1 contract per trade
- Equities: shares + notional + dollars-at-risk; no fake lot terminology
- Crypto: coin quantity + notional + dollars-at-risk; no arbitrary 1.0-coin ceiling
- Instrument hard caps may REDUCE risk-derived size; they may never INCREASE it

---

# Gate architecture

Every strategy entry must survive the applicable sequence:

1. Market/data health
2. Asset/horizon eligibility
3. Completed-bar/horizon-clock eligibility
4. Session eligibility
5. Regime/trend
6. Multi-timeframe alignment
7. Setup detection
8. Trigger confirmation
9. Cost/edge hurdle
10. Duplicate/cooldown protection
11. Event/risk context when validated for enforcement
12. Asset exposure
13. Cluster/correlation exposure
14. Aggregate portfolio risk
15. Instrument hard size limits
16. Paper execution

A downstream gate may veto or reduce a candidate.

A downstream gate may NEVER create a trade when the setup/trigger layer did not produce an executable signal.

---

# Grok bot J.A.R.V.I.S. Coordination Protocol

## GROK BOT J.A.R.V.I.S. — THIS IS THE CANONICAL LOAD-003 CONTROL FILE

Path:

`docs/AETHER_LOAD_003_CONTROL.md`

J.A.R.V.I.S. should read this file first on every LOAD-003 review.

### Rules

1. Only one implementation batch may be ACTIVE.
2. ChatGPT implements and commits only that batch.
3. ChatGPT records the completed batch evidence in THIS FILE.
4. ChatGPT then STOPS.
5. J.A.R.V.I.S. reviews the committed diff, tests, safety boundaries, and evidence.
6. The next batch does not start until J.A.R.V.I.S. explicitly clears it.
7. If J.A.R.V.I.S. finds a defect, repair it inside the CURRENT batch. Do not advance.
8. No weakening/deleting tests merely to obtain green CI.
9. No loosening paper-only/live-blocked safety.
10. No unrelated cleanup/refactor mixed into a batch.
11. Every completed batch must include its SHA and validation evidence.
12. A batch is not DONE simply because code was committed.

### Clearance format

J.A.R.V.I.S. must use:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B<n>`

Example for the first implementation batch:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B1`

If not cleared, J.A.R.V.I.S. should use:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B<n> — <concrete defect/reason>`

ChatGPT must not advance while the batch is on HOLD.

---

# Master Progress

- CONTROL: [COMPLETE] Dedicated LOAD-003 control/checklist established
- B1: [WAITING] Runtime mode separation
- B2: [WAITING] Qualified opportunity pipeline
- B3: [WAITING] Horizon-scoped position ledger
- B4: [WAITING] Portfolio risk & qualified concurrency
- B5: [WAITING] Instrument sizing hard ceilings
- B6: [WAITING] Horizon-specific trade management
- B7: [WAITING] Realistic fill & cost model
- B8: [WAITING] Operator/UI evidence & telemetry
- B9: [WAITING] Integration, deployment contract & closeout

Implementation progress: 0 / 9 batches complete.

---

# B1 — Runtime Mode Separation

## Objective

End the temporary LOAD-002 forced-entry runtime while preserving the execution-validation tools.

## Scope

- Replace the running desk's forced execution-test default with STRATEGY TEST / PAPER behavior.
- Keep the desk armed.
- Keep live execution hard blocked.
- Preserve isolated/manual execution validation.
- Retire legacy LOAD-002 forced positions safely before normal strategy allocation.
- Expose explicit runtime state distinguishing strategy test from execution validation.

## Required proof

- Strategy-test runtime is active.
- Forced execution-test runtime is inactive.
- Desk is armed.
- Existing LOAD-002 test positions retire safely.
- Live order rails remain blocked.
- Execution validation still works separately.
- Relevant unit/regression tests pass.
- CI/deploy evidence recorded when applicable.

## Stop gate

After B1 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B2`

---

# B2 — Qualified Opportunity Pipeline

## Objective

Maximize legitimate setup discovery without manufacturing trade volume.

## Scope

- Evaluate every due supported asset × horizon route.
- Preserve completed-bar/horizon scheduling.
- Require genuine executable signal.
- Remove strategy-test forced signal override.
- Preserve rejection/gate reason for non-trades.
- Rank only already-qualified candidates.
- Preserve valid long/short capability by instrument.

## Required proof

- No setup = no strategy trade.
- Qualified scalp can reach paper entry.
- Qualified intraday can reach paper entry.
- Qualified swing can reach paper entry.
- Rejected routes expose a reason.
- All supported routes remain scheduled.
- Execution-validation overrides cannot leak into strategy mode.

## Stop gate

After B2 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B3`

---

# B3 — Horizon-Scoped Position Ledger

## Objective

Make each asset × horizon independently testable while retaining asset-level risk awareness.

## Scope

- Stable strategy-position identity becomes asset + horizon (or equivalent route key).
- Permit separate qualified positions on different horizons of the same asset.
- Reject duplicate same asset + horizon position.
- Preserve broker/instrument identity for every route position.
- Persist/restore horizon identity.
- Preserve trade IDs, blotter history, and execution-validation identity.

## Required proof

- Same asset can hold two qualified different horizons.
- Duplicate same asset+horizon is rejected.
- Restart restores both horizon positions correctly.
- Closing one horizon does not close/corrupt another.
- Existing history remains readable or has a safe migration.

## Stop gate

After B3 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B4`

---

# B4 — Portfolio Risk & Qualified Concurrency

## Objective

Make portfolio risk, not an arbitrary trade count, the primary concurrency governor.

## Scope

- Enforce <= 0.75% target risk per new position.
- Enforce <= 3.00% aggregate open stop-risk.
- Calculate incremental risk before accepting a candidate.
- Apply asset exposure control.
- Apply cluster/correlation exposure control.
- Permit more than four simultaneous qualified positions when risk/capital permits.
- Preserve cash/margin safeguards.

## Required proof

- >4 qualified low-risk positions can coexist when risk permits.
- Aggregate open risk cannot exceed configured ceiling.
- Exposure limits can reject an otherwise valid setup.
- Risk rejection reason is recorded.
- Cash/margin cannot go negative through normal strategy allocation.

## Stop gate

After B4 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B5`

---

# B5 — Instrument Sizing Hard Ceilings

## Objective

Eliminate ambiguous/weird sizes and enforce explicit per-instrument ceilings.

## Scope

- FX calculates/stores base units and standard lots.
- FX hard cap <= 1.00 standard lot / <= 100,000 base units.
- MES/MNQ/MGC/MCL/US10Y hard cap <= 1 contract each.
- Equities remain share-based with risk/notional controls.
- Crypto remains coin-quantity-based with risk/notional controls.
- Quantity-step rounding remains instrument-correct.
- Hard caps may only reduce calculated size.

## Required proof

- Oversized FX size clips to <= 1.00 lot.
- Each micro future clips to <= 1 contract.
- Stocks/crypto are not incorrectly capped at 1.0 unit.
- API/UI quantity units are unambiguous.
- Below-minimum risk size still produces no trade.

## Stop gate

After B5 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B6`

---

# B6 — Horizon-Specific Trade Management

## Objective

Keep each trade attached to the horizon that earned its entry.

## Scope

- Persist originating horizon/route on every strategy position.
- Scalp uses scalp management/time-stop rules.
- Intraday uses intraday management/time-stop rules.
- Swing/daily-swing use appropriate longer-horizon source bars and timing.
- Preserve structural/hard stops, ATR logic, trailing, rule exits, MFE/MAE.
- Prevent fallback to an unrelated generic primary playbook.
- Manage sibling horizons on one asset independently.

## Required proof

- Scalp remains scalp through exit.
- Intraday remains intraday through exit.
- Swing remains swing through exit.
- Stop/exit changes on one route do not corrupt another.
- Restart preserves management state.

## Stop gate

After B6 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B7`

---

# B7 — Realistic Fill & Cost Model

## Objective

Make paper qualification and P&L reflect realistic execution friction.

## Scope

- Canonical reference price vs modeled fill price.
- Consistent spread, fee, and slippage treatment at entry and exit.
- Instrument-specific fee/contract math.
- Cost/edge hurdle used where applicable before entry.
- Gross P&L, net P&L, fee drag, slippage drag, total cost drag.
- Preserve no-lookahead behavior.
- Live execution remains blocked.

## Required proof

- Deterministic entry/exit cost tests.
- Net P&L reconciles with modeled costs.
- High-friction weak-edge setup can be rejected.
- No double charging or omitted cost leg.
- Existing capture/MFE/MAE analytics remain coherent.

## Stop gate

After B7 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B8`

---

# B8 — Operator/UI Evidence & Telemetry

## Objective

Make strategy-test decisions and risk visible while the system runs.

## Scope

- Display STRATEGY TEST / PAPER clearly.
- Distinguish execution-validation trades from strategy trades.
- Live Trades exposes horizon, side, size, risk, stop, duration, entry reason.
- FX displays units + standard lots.
- Futures display contracts.
- Setup Watch/activity exposes route status and gate/rejection reason.
- Display aggregate open risk and remaining risk capacity.
- Preserve blotter duration/MFE/MAE/capture analytics.

## Required proof

- Validation trade cannot appear as a normal strategy trade.
- Operator can see why a candidate did not trade.
- Operator can identify each open trade's horizon and risk.
- UI/API regressions pass.

## Stop gate

After B8 commit, update this file with SHA + evidence and STOP.

Next batch requires:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B9`

---

# B9 — Integration, Deployment Contract & Closeout

## Objective

Prove the complete LOAD-003 contract in the deployed paper runtime.

## Scope

- Cross-module regression suite.
- Persistence/restart scenarios.
- Simultaneous multi-horizon positions.
- Risk-ceiling exhaustion and recovery.
- No-forced-entry proof.
- Execution-validation isolation proof.
- Live-order hard-block proof.
- CI and Azure deployment checks.
- Deployed runtime status verification.
- Final checklist evidence in this file.

## Final closeout checklist

- [ ] STRATEGY TEST / PAPER runtime active
- [ ] Desk armed
- [ ] Live-money execution hard blocked
- [ ] Global forced execution-test runtime inactive
- [ ] Legacy LOAD-002 positions retired
- [ ] Zero signal creates zero entry
- [ ] All supported horizons scheduled/evaluated
- [ ] Multi-horizon same-asset positions work
- [ ] Duplicate same-route positions blocked
- [ ] >4 qualified positions possible when risk permits
- [ ] Aggregate open risk <= configured ceiling
- [ ] FX <= 1.00 standard lot
- [ ] Micro futures <= 1 contract
- [ ] Originating horizon survives management and exit
- [ ] Spread/fees/slippage reconcile into net P&L
- [ ] Intelligence cannot manufacture a trade
- [ ] Execution validation remains isolated and available
- [ ] Persistence survives restart
- [ ] CI green
- [ ] Azure deploy green
- [ ] Deployed runtime explicitly reports STRATEGY TEST / PAPER
- [ ] Deployed runtime explicitly reports live blocked

LOAD-003 closes only when every applicable item above has committed evidence.

---

# Batch Evidence Log

## CONTROL

Status: COMPLETE

Purpose:
- establish canonical checklist;
- establish Grok stop/clear protocol;
- make no runtime changes.

Starting SHA:
`09dfdb510bd5b54f43cef7e9c5f20389d3636ae1`

### GROK BOT J.A.R.V.I.S. — FIRST ACTION

Review this control file and confirm the load structure and safety boundaries.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B1`

ChatGPT will not start B1 before that clearance.
