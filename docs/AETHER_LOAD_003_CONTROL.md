# AETHER-LOAD-003 — Qualified Trade Throughput & Risk Architecture

## CONTROL STATUS

- Load: AETHER-LOAD-003
- State: B9 COMPLETE — WAITING FOR J.A.R.V.I.S. FINAL REVIEW / LOAD-003 CLOSE
- Active implementation batch: NONE
- Waiting on: GROK BOT J.A.R.V.I.S. FINAL REVIEW / LOAD-003 CLOSE
- Starting main SHA: 09dfdb510bd5b54f43cef7e9c5f20389d3636ae1
- Live-money execution: HARD BLOCKED
- Paper testing: remains the target runtime
- Rule: ONE batch active at a time. Never advance without J.A.R.V.I.S. clearance.

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
- B1: [COMPLETE] Runtime mode separation — d339fb24695dd2738dda8fdb345c6e7a5acf7181
- B2: [COMPLETE] Qualified opportunity pipeline — final head 5c23ca02e514447ea40b8a67bbd5a4de9c37096b
- B3: [COMPLETE] Horizon-scoped position ledger — final head e6ace62d79c2e3d3cf58a29bc141a1f1c7807fb2
- B4: [COMPLETE] Portfolio risk & qualified concurrency — final head 28c33641b7d891ee2e3f64793102ff2d04703800
- B5: [COMPLETE] Instrument sizing hard ceilings — 151ad2fb2e2a5a5648b18cfe3393dcf7ff6d596c
- B6: [COMPLETE] Horizon-specific trade management — final head d7089c2d85c623020136bd445a57183a74021073
- B7: [COMPLETE] Realistic fill & cost model — final head 102746f16b30239e48912dd5f8b6895340a06c03
- B8: [COMPLETE] Operator/UI evidence & telemetry — final head 914884c65645102e6c0115ef1214f1f8a3be13a9
- B9: [COMPLETE] Integration, deployment contract & closeout — final head ba888fc6b550b08b1095b051e209d5a2c0b2e82f

Implementation progress: 9 / 9 batches complete.

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

- [x] STRATEGY TEST / PAPER runtime active
- [x] Desk armed
- [x] Live-money execution hard blocked
- [x] Global forced execution-test runtime inactive
- [x] Legacy LOAD-002 positions retired
- [x] Zero signal creates zero entry
- [x] All supported horizons scheduled/evaluated
- [x] Multi-horizon same-asset positions work
- [x] Duplicate same-route positions blocked
- [x] >4 qualified positions possible when risk permits
- [x] Aggregate open risk <= configured ceiling
- [x] FX <= 1.00 standard lot
- [x] Micro futures <= 1 contract
- [x] Originating horizon survives management and exit
- [x] Spread/fees/slippage reconcile into net P&L
- [x] Intelligence cannot manufacture a trade
- [x] Execution validation remains isolated and available
- [x] Persistence survives restart
- [x] CI green
- [x] Azure deploy green
- [x] Deployed runtime explicitly reports STRATEGY TEST / PAPER
- [x] Deployed runtime explicitly reports live blocked

LOAD-003 closes only when every applicable item above has committed evidence.

---

# Batch Evidence Log

## CONTROL

Status: COMPLETE

Purpose:
- establish canonical checklist;
- establish J.A.R.V.I.S. stop/clear protocol;
- make no runtime changes.

Starting SHA:
`09dfdb510bd5b54f43cef7e9c5f20389d3636ae1`

### GROK BOT J.A.R.V.I.S. — FIRST ACTION

Review this control file and confirm the load structure and safety boundaries.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B1`

ChatGPT will not start B1 before that clearance.


## B1 — Runtime Mode Separation

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Implementation SHA:
`d339fb24695dd2738dda8fdb345c6e7a5acf7181`

Commit:
`feat: separate strategy test from execution validation`

Scope completed:
- production desk now starts with `execution_test_mode=False`;
- desk remains armed;
- explicit runtime mode reports `strategy_test`;
- explicit execution-validation mode remains available for isolated LOAD-002 validation;
- forced-entry state is explicitly reported and is OFF in strategy-test runtime;
- paper mode remains active;
- live-money execution remains HARD BLOCKED;
- existing legacy LOAD-002 retirement path remains before normal allocation;
- deployment contract now requires strategy-test runtime and rejects a forced-execution production state;
- LOAD-002 status remains available but reports its forced experiment inactive in the production strategy-test runtime.

Safety evidence:
- `live_blocked=True`;
- `strategy_test_mode=True`;
- `execution_validation_mode=False` in production;
- `execution_test_mode=False` in production;
- `forced_entries_enabled=False` in production;
- isolated execution validation still reports `execution_validation` when explicitly instantiated with `execution_test_mode=True`.

Validation evidence:
- CI run #436 — SUCCESS;
- Azure workflow run #319 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployment verification asserted release `AETHER-LOAD-003-B1`;
- deployment verification asserted runtime mode `strategy_test`;
- deployment verification asserted forced entries OFF;
- deployment verification asserted live execution blocked;
- execution matrix endpoint remained present and validated as isolated execution tooling.

Files changed by implementation SHA:
- `backend/app/desk.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- qualified opportunity routing changes — B2;
- horizon-scoped ledger — B3;
- portfolio concurrency/risk architecture — B4;
- instrument hard size ceilings — B5;
- horizon-specific management changes — B6;
- realistic fill/cost model changes — B7;
- operator/UI evidence changes — B8;
- final integration/closeout — B9.

### J.A.R.V.I.S. REVIEW GATE

Review implementation SHA `d339fb24695dd2738dda8fdb345c6e7a5acf7181` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B2`

If a B1 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B1 — <concrete defect/reason>`

ChatGPT must not start B2 without the explicit B2 clearance.

## B2 — Qualified Opportunity Pipeline

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Final implementation head:
`5c23ca02e514447ea40b8a67bbd5a4de9c37096b`

B2 commits:
- `8838c33700b2ee7ebfbb58ffaf92d2ade8d0aa04` — `feat: qualify every due strategy route`
- `5c23ca02e514447ea40b8a67bbd5a4de9c37096b` — `fix: preserve isolated execution validation fills`

Scope completed:
- strategy-test allocator evaluates every due supported asset × horizon route;
- current configuration is proven as 28 supported asset × horizon evaluations when all clocks are due;
- every evaluated route records strategy attribution, signal/executable signal, quality, setup reason, execution status, and final pipeline status;
- non-qualified setups are retained as explicit `rejected` evaluations instead of disappearing;
- strategy exceptions are retained as explicit `error` evaluations;
- qualified routes are the only routes admitted to candidate ranking;
- when multiple horizons qualify for the same asset under the current pre-B3 ledger, lower-ranked qualified routes are explicitly blocked as `lower_ranked_same_asset_route` rather than silently discarded;
- qualified routes blocked by current downstream limits retain explicit reasons such as `position_already_open`, `active_position_limit`, `cluster_cap`, `no_mark`, `risk_or_capital_unavailable`, or `execution_rejected:<reason>`;
- qualified scalp, intraday, and swing routes are proven able to reach paper entry;
- supported short direction is proven able to reach an actual paper short position;
- opportunity evaluation evidence persists/restores with desk state;
- explicit LOAD-002 forced-execution override is proven unable to leak into strategy-test routing;
- existing isolated execution-validation fills retain immediate persistence.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- `execution_test_mode=False` in production;
- `forced_entries_enabled=False` in production;
- no executable signal means no strategy entry;
- live-money execution remains HARD BLOCKED;
- isolated execution validation remains available and separate;
- one-position-per-asset behavior is intentionally unchanged and remains deferred to B3;
- fixed concurrency/risk architecture is intentionally unchanged and remains deferred to B4;
- sizing ceilings are intentionally unchanged and remain deferred to B5.

Validation evidence on final B2 head:
- CI run #439 — SUCCESS;
- Azure workflow run #322 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B2`;
- deployed runtime asserted `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked.

Key B2 regression proofs:
- all 28 supported asset × horizon routes evaluated when all route clocks are due;
- rejected routes retain their gate reason;
- qualified scalp route reaches paper entry;
- qualified intraday route reaches paper entry;
- qualified swing route reaches paper entry;
- supported short route reaches paper short entry;
- forced execution override cannot leak into strategy mode;
- opportunity evaluation evidence survives restore.

Files changed by B2:
- `backend/app/desk.py`
- `backend/tests/test_routing.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- horizon-scoped position ledger — B3;
- portfolio risk & qualified concurrency — B4;
- instrument sizing hard ceilings — B5;
- horizon-specific trade management — B6;
- realistic fill/cost model — B7;
- operator/UI evidence & telemetry — B8;
- final integration/deployment closeout — B9.

### J.A.R.V.I.S. REVIEW GATE

Review final B2 head `5c23ca02e514447ea40b8a67bbd5a4de9c37096b` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B3`

If a B2 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B2 — <concrete defect/reason>`

ChatGPT must not start B3 without the explicit B3 clearance.

## B3 — Horizon-Scoped Position Ledger

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Final implementation head:
`e6ace62d79c2e3d3cf58a29bc141a1f1c7807fb2`

B3 commit chain:
- `317f481f9f941c32d8aae2e966b59619a80a56ba` — `feat: scope paper positions by trading horizon`
- `a059136f398799eddfc8919a47e709b32e61d12d` — B3 syntax repair in paper portfolio
- `aa2e3bb2a96b3df4f2092cfa3f579d73a0e745ba` — B3 syntax repair in route PairBook
- `e6ace62d79c2e3d3cf58a29bc141a1f1c7807fb2` — `test: adapt routing probes to horizon-scoped books`

Scope completed:
- strategy positions now use stable route identity `asset:horizon`, such as `nvda:scalp`, `nvda:intraday`, and `nvda:swing`;
- underlying `asset_id` remains the canonical instrument identity for pricing, fees, P/L, margin, broker/product semantics, and analytics;
- the paper portfolio supports multiple simultaneous positions for the same asset when their horizon keys differ;
- duplicate opens of the same exact asset+horizon route are rejected;
- position lookup, quantity, average entry, side, P/L, notional, stop updates, and close operations are route-key aware;
- each asset+horizon receives an independent route PairBook execution state;
- route books share market data bars with the canonical asset book but keep independent stop, high/low excursion state, entry timestamp, entry mode, signal key, and fill history;
- strategy allocation now admits independently qualified routes into the existing downstream limits instead of collapsing them to one candidate per asset;
- closing one route does not close or corrupt a sibling horizon position;
- route position identity and route PairBook state persist and restore across restart;
- legacy normal strategy positions keyed only by asset are migrated to an inferred supported horizon using saved routing/mode data with a safe primary-horizon fallback;
- legacy/LOAD-002 execution-validation positions retain exact asset-key identity and remain isolated;
- Live Trades enumerates actual route positions and exposes their `position_key`;
- trade/event records preserve route identity.

Required B3 proof:
- same asset can hold two different horizon positions — PROVEN;
- duplicate same asset+horizon is rejected — PROVEN;
- restart restores independent sibling horizon positions/state — PROVEN;
- closing one horizon leaves sibling horizon open — PROVEN;
- legacy normal strategy position migration retains the original trade — PROVEN;
- B2 route qualification behavior remains intact on route-scoped books — PROVEN.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- live-money execution remains HARD BLOCKED;
- forced strategy entries remain OFF;
- isolated execution validation remains available separately;
- B4 portfolio-risk/concurrency policy was NOT implemented in B3;
- existing `MAX_ACTIVE_POSITIONS` and cluster caps remain in force pending B4;
- B5 instrument size ceilings were NOT pulled forward;
- B6 management-policy changes were NOT pulled forward.

Validation evidence on final B3 head:
- CI run #443 — SUCCESS;
- final backend suite — 226 passed, 1 warning;
- Azure workflow run #326 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B3`;
- deployed runtime remained `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked.

Repair evidence:
- CI #440 caught malformed syntax in the first atomic B3 patch; repaired inside B3 without weakening tests;
- CI #442 then caught six preserved B2 routing probes still injecting mocks into pre-B3 base books; the tests were adapted to the new route-scoped objects while retaining the same behavioral assertions;
- final CI #443 is green after those repairs.

Files changed by B3:
- `backend/app/paper_portfolio.py`
- `backend/app/pair_book.py`
- `backend/app/desk.py`
- `backend/tests/test_horizon_position_ledger.py`
- `backend/tests/test_routing.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- portfolio risk & qualified concurrency — B4;
- instrument sizing hard ceilings — B5;
- horizon-specific management policy changes — B6;
- realistic fill/cost model — B7;
- operator/UI evidence & telemetry — B8;
- final integration/deployment closeout — B9.

### J.A.R.V.I.S. REVIEW GATE

Review final B3 head `e6ace62d79c2e3d3cf58a29bc141a1f1c7807fb2` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B4`

If a B3 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B3 — <concrete defect/reason>`

ChatGPT must not start B4 without the explicit B4 clearance.

## B4 — Portfolio Risk & Qualified Concurrency

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Final implementation head:
`28c33641b7d891ee2e3f64793102ff2d04703800`

B4 commit chain:
- `e0f345eac13c0312bb1cc90a737fd8fd04ee92b4` — `feat: govern qualified concurrency by portfolio risk`
- `c5312d5aff4906d8568d259f531bd2e594991f72` — `fix: keep unopened horizon lookup route-scoped`
- `5ef7302f07c10a1e4518a2aae04cd4aa1d3a0d0f` — `test: correct B4 risk fixtures to market marks`
- `28c33641b7d891ee2e3f64793102ff2d04703800` — `test: anchor B4 exposure limit to current equity`

B4 risk policy:
- maximum target risk per new strategy trade: 0.75% of current paper equity;
- maximum aggregate open stop-risk: 3.00% of current paper equity;
- maximum per-asset open stop-risk: 1.50% of current paper equity;
- maximum per-cluster open stop-risk: 2.25% of current paper equity;
- the former fixed four-position strategy cap is removed;
- exposure ceilings are expressed in stop-risk dollars rather than raw position counts;
- execution-validation mode remains separately bounded and is not governed by the strategy concurrency contract.

Scope completed:
- canonical stop-risk math is available for planned and open paper positions across supported instrument types;
- stop-risk is measured from entry to the active stop using instrument-aware P/L semantics;
- profitable/trailing stops at or beyond breakeven contribute zero remaining downside stop-risk rather than a false absolute-risk value;
- the allocator recalculates current paper equity and open-risk capacity before accepting each qualified candidate;
- new strategy sizing is bounded by the minimum remaining capacity across trade, asset, cluster, aggregate portfolio, and capital constraints;
- actual post-rounding candidate stop-risk is independently checked before the order is opened;
- qualified candidates can be reduced to remaining risk capacity rather than requiring a full 0.75% target;
- asset exposure can veto a qualified route when the 1.50% asset-risk ceiling is exhausted;
- cluster/correlation exposure can veto a qualified route when the 2.25% cluster-risk ceiling is exhausted;
- aggregate portfolio exposure can veto a qualified route when the 3.00% open-risk ceiling is exhausted;
- risk-gate rejection reasons and relevant risk values are retained on opportunity evaluations;
- successful strategy entries persist target risk, initial stop-risk, and pre-entry portfolio/asset/cluster risk context in position metadata;
- the previous `MAX_ACTIVE_POSITIONS = 4` strategy governor is removed;
- more than four qualified low-risk positions are permitted when stop-risk and capital permit;
- cash/margin remains enforced by the paper portfolio; normal strategy entries cannot borrow validation-only overflow capital;
- the allocator recomputes the capital cap from current free paper cash before each entry;
- B3 route isolation was hardened so an explicit unopened route key such as `nvda:swing` does not inherit aggregate quantity from open sibling horizons.

Required B4 proof:
- >4 qualified low-risk positions can coexist when risk permits — PROVEN;
- aggregate open stop-risk cannot exceed the configured 3.00% ceiling — PROVEN;
- asset exposure limit can reject an otherwise qualified route — PROVEN;
- cluster/correlation exposure limit can reject an otherwise qualified route — PROVEN;
- risk rejection reason is recorded — PROVEN;
- per-trade stop-risk remains <= 0.75% of current paper equity — PROVEN;
- normal paper allocation leaves cash nonnegative and validation overflow at zero — PROVEN;
- explicit unopened route lookup remains horizon-scoped with sibling positions present — PROVEN;
- fixed four-position strategy limit is absent from the machine-visible B4 policy — PROVEN.

Machine-visible policy:
- `max_trade_risk_pct = 0.75`;
- `max_asset_risk_pct = 1.50`;
- `max_cluster_risk_pct = 2.25`;
- `max_portfolio_risk_pct = 3.00`;
- `fixed_strategy_position_limit = null`.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- live-money execution remains HARD BLOCKED;
- forced strategy entries remain OFF;
- isolated LOAD-002 execution validation remains available;
- validation-only buying-power overflow does not apply to normal strategy allocation;
- B5 instrument hard ceilings were NOT implemented in B4;
- B6 horizon-specific management changes were NOT implemented in B4;
- B7 cost-model changes were NOT pulled forward.

Validation evidence on final B4 head:
- CI run #447 — SUCCESS;
- final backend suite — 232 passed, 1 warning;
- Azure workflow run #330 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B4`;
- deployed runtime remained `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked.

Repair evidence:
- the first B4 validation exposed test fixtures that seeded large synthetic holdings and unintentionally exhausted cash before the aggregate-risk assertion;
- B4 validation also exposed a real B3 ledger edge case where an explicit unopened horizon lookup fell back to aggregate same-asset quantity; this was repaired in B4 because it directly affected qualified concurrency/exposure gating;
- subsequent validation showed one assertion using nominal starting equity instead of current equity after entry fees; the assertion was corrected to the runtime's current-equity basis;
- CI #446 and Azure #329 were correctly red on the pre-final repair head;
- final CI #447 and Azure #330 are green on `28c33641b7d891ee2e3f64793102ff2d04703800`.

Files changed by B4:
- `backend/app/paper_portfolio.py`
- `backend/app/pair_book.py`
- `backend/app/desk.py`
- `backend/tests/test_portfolio_risk.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- FX 1.00-standard-lot and 100,000-base-unit hard ceilings — B5;
- one-contract hard ceilings for MES/MNQ/MGC/MCL/US10Y — B5;
- equity/crypto instrument-specific hard sizing ceilings — B5;
- horizon-specific management policy changes — B6;
- realistic fill/cost model — B7;
- operator/UI risk display — B8;
- final integration/deployment closeout — B9.

### J.A.R.V.I.S. REVIEW GATE

Review final B4 head `28c33641b7d891ee2e3f64793102ff2d04703800` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B5`

If a B4 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B4 — <concrete defect/reason>`

ChatGPT must not start B5 without the explicit B5 clearance.

## B5 — Instrument Sizing Hard Ceilings

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Implementation SHA:
`151ad2fb2e2a5a5648b18cfe3393dcf7ff6d596c`

Commit:
`feat: enforce instrument sizing ceilings`

Scope completed:
- EURUSD and USDJPY hard cap at 100,000 base units / 1.00 standard lot per trade;
- both FX specifications define `standard_lot_units=100000`, `max_standard_lots=1.0`, and `max_quantity=100000`;
- MES, MNQ, MGC, MCL, and US10Y hard cap at 1 contract per trade;
- hard caps are applied after risk/capital sizing, so they may only reduce the risk-derived size and can never increase it;
- paper `open_position` reapplies the same ceiling as a final invariant, protecting direct/internal paper calls from oversized requests;
- quantity-step rounding remains instrument-specific;
- FX paper positions persist raw base units and derived standard lots;
- futures persist contracts;
- equities persist shares;
- crypto persists coin quantity;
- equities and crypto intentionally have no blanket 1.0-unit hard cap;
- restored open positions are backfilled with the canonical quantity metadata;
- PairBook entry plans and views expose unambiguous quantity units;
- Live Trades API output carries base units/standard lots/contracts/shares/coin quantity as applicable;
- machine-visible settings expose the B5 sizing contract.

Machine-visible sizing policy:
- `fx_max_standard_lots = 1.0`;
- `fx_max_base_units = 100000.0`;
- `micro_future_max_contracts = 1.0`;
- `equity_quantity_unit = shares`;
- `crypto_quantity_unit = coin_quantity`.

Required B5 proof:
- oversized FX risk sizing clips to <= 100,000 base units / <= 1.00 standard lot — PROVEN;
- direct oversized FX paper request is clipped to 100,000 base units and stores `standard_lots=1.0` — PROVEN;
- MES hard cap <= 1 contract — PROVEN;
- MNQ hard cap <= 1 contract — PROVEN;
- MGC hard cap <= 1 contract — PROVEN;
- MCL hard cap <= 1 contract — PROVEN;
- US10Y hard cap <= 1 contract — PROVEN;
- equities can size/open above 1 share when risk and capital allow — PROVEN;
- crypto can size/open above 1 coin when risk and capital allow — PROVEN;
- below-minimum risk sizing still returns zero quantity/no trade — PROVEN;
- FX and futures entry plans expose unambiguous unit metadata — PROVEN;
- hard caps do not replace B4 risk sizing; they only constrain its output — PROVEN.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- forced strategy entries remain OFF;
- live-money execution remains HARD BLOCKED;
- isolated LOAD-002 execution validation remains available;
- B4 per-trade/asset/cluster/portfolio risk ceilings remain in force;
- B6 horizon-specific management changes were NOT implemented;
- B7 fill/cost changes were NOT implemented;
- B8 visual/operator UI changes were NOT pulled forward beyond API quantity metadata required by B5.

Validation evidence:
- CI run #448 — SUCCESS;
- final backend suite — 239 passed, 1 warning;
- Azure workflow run #331 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B5`;
- deployed runtime remained `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked.

Files changed by B5:
- `backend/app/instruments.py`
- `backend/app/paper_portfolio.py`
- `backend/app/pair_book.py`
- `backend/app/desk.py`
- `backend/tests/test_instrument_sizing_limits.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- horizon-specific management policy — B6;
- realistic fill/cost model — B7;
- full operator/UI evidence presentation — B8;
- integration/deployment closeout — B9.

### J.A.R.V.I.S. REVIEW GATE

Review implementation SHA `151ad2fb2e2a5a5648b18cfe3393dcf7ff6d596c` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B6`

If a B5 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B5 — <concrete defect/reason>`

ChatGPT must not start B6 without the explicit B6 clearance.

## B6 — Horizon-Specific Trade Management

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Final implementation head:
`d7089c2d85c623020136bd445a57183a74021073`

B6 commit chain:
- `ba7db244ceb9f5aec3186e5b4d1b7e23417f0bfb` — `feat: bind trade management to entry horizon`
- `d7089c2d85c623020136bd445a57183a74021073` — `test: isolate sibling horizon stop management`

Scope completed:
- every strategy route now has an explicit management contract derived from its route identity;
- route identity is authoritative over a conflicting saved `entry_mode` or stale metadata;
- scalp routes manage as `scalp` on 1-minute source bars with the configured 15-minute time stop;
- intraday routes manage as `intraday` on completed 15-minute bars with the instrument-specific intraday time stop;
- swing routes manage as `swing` on 1-hour bars with the instrument-specific swing time stop;
- BTC/ETH `swing` route identity maps canonically to `daily_swing` management on 1-day bars;
- originating horizon, management mode, management clock, and management time-stop contract are exposed on route/book and Live Trades state;
- new strategy entries persist `originating_horizon` and canonical `management_mode` in position metadata;
- legacy normal strategy migration backfills `originating_horizon` and canonical `management_mode`;
- execution-validation positions remain isolated and deliberately use the asset's valid primary playbook rather than an invalid `execution_test` strategy mode;
- the existing structural/hard stop, ATR-aware long exit plan, short trailing logic, time stop, rule exit, MFE/MAE, capture, slippage, and fee analytics remain intact;
- sibling horizons on one asset retain independent stops and execution state;
- restart restores route stop/high/low/entry state and the same horizon-specific management contract;
- a route horizon cannot silently fall back to an unrelated asset primary when the route identity is present.

Required B6 proof:
- scalp remains scalp through management — PROVEN;
- intraday remains intraday through management — PROVEN;
- swing remains swing through management — PROVEN;
- BTC/ETH swing maps to daily-swing management — PROVEN;
- route identity overrides conflicting saved entry-mode metadata — PROVEN;
- management requests the originating horizon playbook — PROVEN;
- stop movement on one horizon does not mutate a sibling horizon — PROVEN;
- restart preserves route management identity and stop/excursion state — PROVEN;
- execution validation never requests `execution_test` as a strategy playbook — PROVEN.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- forced strategy entries remain OFF;
- live-money execution remains HARD BLOCKED;
- isolated LOAD-002 execution validation remains available;
- B4 risk ceilings remain in force;
- B5 instrument hard size ceilings remain in force;
- B7 fill/cost model changes were NOT implemented in B6;
- B8 operator/UI work was NOT pulled forward beyond management metadata needed for B6 evidence.

Validation evidence on final B6 head:
- CI run #450 — SUCCESS;
- final backend suite — 246 passed, 1 warning;
- Azure workflow run #333 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B6`;
- deployed runtime remained `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked.

Repair evidence:
- before final validation, the sibling-stop regression fixture was corrected so its synthetic 1-minute bar did not falsely cross the newly trailed scalp stop;
- this repair changed only the test fixture and did not loosen production management behavior or assertions;
- final CI #450 and Azure #333 are green on `d7089c2d85c623020136bd445a57183a74021073`.

Files changed by B6:
- `backend/app/pair_book.py`
- `backend/app/desk.py`
- `backend/tests/test_horizon_management.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- realistic spread/fee/slippage and cost-edge model — B7;
- full operator/UI evidence presentation — B8;
- final cross-module integration/deployment closeout — B9.

### J.A.R.V.I.S. REVIEW GATE

Review final B6 head `d7089c2d85c623020136bd445a57183a74021073` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B7`

If a B6 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B6 — <concrete defect/reason>`

ChatGPT must not start B7 without the explicit B7 clearance.

## B7 — Realistic Fill & Cost Model

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Final validation head:
`102746f16b30239e48912dd5f8b6895340a06c03`

B7 commit chain:
- `a7921a6bbbc7f7ac2b73a55b8ae501b67a30a8f0` — `refactor: canonicalize paper fill references [skip ci]`
- `9f91d14d30b73b0b72fdeef81282eca69869f01b` — `refactor: share canonical modeled fill price [skip ci]`
- `30cba62222f986c6eb51218293444d327f1771ed` — `feat: add instrument-aware execution cost ledger [skip ci]`
- `b3a47e341c295f1f606a2449722b4bf24eba6aaf` — `feat: expose route opportunity for cost hurdle [skip ci]`
- `b9d2fbfcb841fa6eb7a42e5d542a75d0f595c381` — `feat: apply actual-sized cost hurdle at entry [skip ci]`
- `20c7373a978960ea66892ffccc8beba14136aaff` — `feat: reconcile entry exit friction and net pnl [skip ci]`
- `279d74aa508ba34bde13ee46d26756c7e5e19c18` — `feat: record modeled cost hurdle decisions [skip ci]`
- `96d6733c0d8d260cbb36f25a1f80451b0a8aede3` — `test: advance execution safety contract to B7 [skip ci]`
- `6ec9eb416aa8ec6da687b534b9c06525787b0e4c` — `test: advance deployment assertions to B7 [skip ci]`
- `0dc32620efe754326177a3c9896e6333e13281d6` — `ci: verify B7 production runtime [skip ci]`
- `19fd7b15640aac8c5c385df9a5ed72310e5f4987` — `fix: use actual open quantity for management costs [skip ci]`
- `102746f16b30239e48912dd5f8b6895340a06c03` — `test: prove realistic paper cost reconciliation`

Scope completed:
- one canonical deterministic paper-fill model now separates neutral market reference, crossed quote reference, and adverse-slippage fill price;
- modeled slippage remains 5 bps per execution leg;
- pre-entry transaction cost is calculated after risk/capital/hard-cap sizing, using the actual final quantity rather than a one-unit placeholder;
- the entry cost model includes observed spread, modeled adverse slippage, and instrument-specific fees;
- weak-edge strategy setups can be rejected by `edge_below_cost_hurdle` before a paper position is opened;
- cost hurdle uses a 1.40x modeled round-trip cost multiple against the route's observable opportunity envelope;
- route opportunity percentage is exposed for scalp, intraday, swing, and crypto daily-swing routes using only available bars;
- paper positions persist market reference, quote reference, fill price, entry spread, entry slippage, modeled round-trip cost, cost hurdle, and opportunity percentage;
- exit accounting uses the same market/quote/fill separation and opposite execution side appropriate to long or short positions;
- FX observed bid/ask spread is the FX transaction-cost representation and is not charged again as a synthetic FX fee;
- equity commissions remain quantity-aware under the existing IBKR model;
- futures fees remain contract-aware under the existing NinjaTrader per-side model, while spread/slippage P&L uses the instrument point value;
- crypto continues to use the existing Kraken taker-fee model;
- management-time cost percentage now uses the actual open quantity through the same canonical round-trip estimator when available;
- closed trades expose spread drag, slippage drag, fee drag, total cost drag, and a direct dollar reconciliation check;
- canonical reconciliation is `reference_pnl - spread - slippage - fees = net_pnl`;
- existing MFE/MAE, capture efficiency, missed-opportunity, and entry/exit efficiency analytics remain in place;
- opportunity evaluations retain cost-hurdle values and the direct `edge_below_cost_hurdle` rejection reason.

Required B7 proof:
- neutral market reference, quote-cross price, and modeled fill are distinct and deterministic — PROVEN;
- entry and exit slippage are adverse by execution side — PROVEN;
- equity fees use actual final quantity — PROVEN;
- futures transaction friction uses contract fees and point-value P&L semantics — PROVEN;
- FX spread is not double-charged as a separate fee — PROVEN;
- high-friction / weak-edge setup can be rejected before entry — PROVEN;
- a setup whose opportunity clears the same hurdle can proceed — PROVEN;
- long trade reference/gross/net P&L reconciles with spread, slippage, and fees — PROVEN;
- short trade uses opposite execution sides and reconciles through the same model — PROVEN;
- no cost leg is omitted or double charged in final reconciliation — PROVEN.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- forced strategy entries remain OFF;
- live-money execution remains HARD BLOCKED;
- isolated LOAD-002 execution validation remains available;
- B4 portfolio/asset/cluster risk ceilings remain intact;
- B5 hard sizing ceilings remain intact;
- B6 horizon-specific management remains intact;
- B8 operator/UI presentation was NOT implemented in B7;
- B9 final integration closeout was NOT pulled forward.

Validation evidence on final B7 head:
- CI run #451 — SUCCESS;
- final backend suite — 254 passed, 1 warning;
- Azure workflow run #334 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B7`;
- deployed runtime remained `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked.

Execution note:
- the first attempted all-in-one B7 commit exceeded the GitHub orchestration call ceiling before mutation;
- main was immediately verified unchanged at the B6 evidence tip before continuing;
- B7 was then split into deterministic B7-only commits, with intermediate commits marked `[skip ci]` and the final validation head receiving the full CI/Azure run;
- no B8 or B9 implementation was started.

### J.A.R.V.I.S. REVIEW GATE

Review final B7 head `102746f16b30239e48912dd5f8b6895340a06c03` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B8`

If a B7 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B7 — <concrete defect/reason>`

ChatGPT must not start B8 without the explicit B8 clearance.

## B8 — Operator/UI Evidence & Telemetry

Status: COMPLETE — VERIFIED/CLEARED BY J.A.R.V.I.S.

Final validation head:
`914884c65645102e6c0115ef1214f1f8a3be13a9`

B8 commit chain:
- `b2491176a7e31d19c017dccb1157f50fa84ca2b5` — `feat: expose operator strategy telemetry [skip ci]`
- `0f09964191e4048e08415515c90d4dcc45344257` — `ui: add B8 operator telemetry surfaces [skip ci]`
- `56623d3cabe22c18e5c47bb25dd5b7e777e8c631` — `ui: render strategy risk and route evidence [skip ci]`
- `97c237acd27b290f09e9c82eb5e96ebcd3ce0de0` — `ui: style strategy and validation telemetry [skip ci]`
- `0e1f32a62513cf2271a26387c356e02994e8f2df` — `test: advance execution safety contract to B8 [skip ci]`
- `b7da3808da263acd828f6c63b9f34f173165794e` — `test: advance deployment assertions to B8 [skip ci]`
- `376a3a87de1fdb56719731006d2e13f91c677482` — `test: prove B8 operator UI evidence [skip ci]`
- `831d4dcd0e949c47088e02d55a302b93da4c3617` — `ci: verify B8 operator telemetry in production [skip ci]`
- `914884c65645102e6c0115ef1214f1f8a3be13a9` — `test: prove B8 operator telemetry and trade identity`

Scope completed:
- Live Trades API now exposes explicit runtime state, strategy-test/paper identity, forced-entry state, live-block state, and strategy-vs-validation open counts;
- every open trade is explicitly classified as `strategy` or `execution_validation`;
- execution-validation positions retain `execution_test=true`, LOAD-002 identity, and the normal strategy gate that would have blocked the forced validation fill;
- strategy positions expose position/route key, originating horizon, management mode/clock, current stop-risk dollars, stop-risk as percent of current equity, target risk, entry reason, and quality;
- FX open trades expose raw base units plus standard lots;
- futures expose contracts;
- equities expose shares;
- crypto exposes coin quantity;
- Live Trades exposes modeled cost/opportunity/hurdle telemetry from B7 when available;
- Setup Watch now uses the latest actual asset × horizon opportunity evaluations instead of one generic base-book snapshot per asset;
- Setup Watch exposes route key, route status, signal, quality, cost/hurdle fields when available, and the final gate/rejection reason;
- live runtime response exposes aggregate open strategy stop-risk, remaining portfolio-risk capacity, and configured maximum portfolio risk;
- Floor portfolio response also includes the same strategy-risk snapshot;
- UI clearly displays `STRATEGY TEST / PAPER` vs `EXECUTION VALIDATION`;
- validation trades receive a distinct amber operator treatment and cannot visually masquerade as normal strategy positions;
- Live Trade cards show route/horizon, side, duration, entry/current/stop, exact quantity units, current risk, MFE/MAE, management identity, entry reason, and cost/edge evidence;
- Setup Watch visibly renders latest route decision status and reason;
- Blotter now renders trade class, horizon, duration, return, MFE, MAE, capture efficiency, and total modeled cost drag while retaining historical rows;
- top-level static asset cache marker advanced to `AETHER-LOAD-003-B8`;
- production deploy verification checks the actual B8 HTML/JS release marker and the deployed `/api/v1/desk/live-trades` telemetry contract.

Required B8 proof:
- execution-validation trade cannot appear as a normal strategy trade — PROVEN;
- mixed strategy + validation positions remain separately counted/classified — PROVEN;
- validation-only position risk is excluded from strategy portfolio-risk telemetry — PROVEN;
- operator can see each strategy trade's route/horizon and stop-risk — PROVEN;
- FX API/UI evidence includes base units + standard lots — PROVEN;
- futures API/UI evidence includes contracts — PROVEN;
- operator can see why a candidate did not trade through route gate/rejection reason — PROVEN;
- Setup Watch preserves modeled cost/hurdle evidence when present — PROVEN;
- aggregate open risk, remaining capacity, and max portfolio risk are visible — PROVEN;
- Blotter preserves and displays duration/MFE/MAE/capture/cost analytics — PROVEN;
- deployed UI uses the B8 cache-busted assets and deployed API reports the B8 telemetry contract — PROVEN.

Safety/invariant evidence:
- production runtime remains `strategy_test`;
- desk remains paper-mode;
- forced strategy entries remain OFF;
- live-money execution remains HARD BLOCKED;
- LOAD-002 execution validation remains isolated and visibly labeled;
- B4 risk ceilings remain intact;
- B5 instrument hard ceilings remain intact;
- B6 horizon-specific management remains intact;
- B7 realistic fill/cost reconciliation remains intact;
- B9 final integration/closeout was NOT started.

Validation evidence on final B8 head:
- CI run #452 — SUCCESS;
- final backend/UI regression suite — 260 passed, 1 warning;
- browser JavaScript syntax check — SUCCESS;
- Azure workflow run #335 — SUCCESS;
- Azure build backend tests — SUCCESS;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- deployed release asserted `AETHER-LOAD-003-B8`;
- deployed runtime remained `strategy_test`;
- deployed runtime asserted forced entries OFF;
- deployed runtime asserted live execution blocked;
- deployed root HTML asserted B8 release marker;
- deployed JS asserted strategy/validation labels, risk telemetry, unit telemetry, and Blotter analytics;
- deployed Live Trades endpoint asserted runtime, risk, item/watch/event schema and classification invariants.

Files changed by B8:
- `backend/app/desk.py`
- `backend/app/static/index.html`
- `backend/app/static/aether-app.js`
- `backend/app/static/aether-app.css`
- `backend/tests/test_operator_telemetry.py`
- `backend/tests/test_live_ui.py`
- `backend/tests/test_execution_test_mode.py`
- `backend/tests/test_load_002_closeout.py`
- `.github/workflows/main_aether-prod-api.yml`

Not changed / deferred:
- final cross-module LOAD-003 integration closeout — B9;
- no live-money enablement;
- no new strategy/gate logic;
- no risk-ceiling changes;
- no sizing-ceiling changes;
- no management-policy changes.

### J.A.R.V.I.S. REVIEW GATE

Review final B8 head `914884c65645102e6c0115ef1214f1f8a3be13a9` and the evidence above.

If clear, respond exactly:

`J.A.R.V.I.S. CLEAR — AETHER-LOAD-003 — START B9`

If a B8 defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B8 — <concrete defect/reason>`

ChatGPT must not start B9 without the explicit B9 clearance.

## B9 — Integration, Deployment Contract & Closeout

Status: COMPLETE — WAITING FOR J.A.R.V.I.S. FINAL REVIEW / LOAD-003 CLOSE

Final validated implementation head:
`ba888fc6b550b08b1095b051e209d5a2c0b2e82f`

B9 commit chain:
- `44ccb85a705646ff1a4e9ddd25ada33aea6d1875` — `chore: mark AETHER LOAD 003 final runtime [skip ci]`
- `2f1804f9c588ca1fdfcee78d862f253c4f5d7d10` — `ui: mark AETHER LOAD 003 final release [skip ci]`
- `0865598dad9e8cefeaca49cf2e46365fc8bf3cf0` — `test: advance execution safety contract to B9 [skip ci]`
- `b5d7027afa5a5acdd84105410d23f6992282ae38` — `test: advance operator telemetry contract to B9 [skip ci]`
- `f2f7eb2b491e206153718d0d7d75ad0eb11f02aa` — `test: advance UI release contract to B9 [skip ci]`
- `4b7269e75eb7f874b599285ebadfef4cdaf85fa3` — `test: advance deployment contract to B9 [skip ci]`
- `cf916246655efa7cdd9f60bf08a7441c64387b36` — `test: integrate AETHER LOAD 003 closeout contract [skip ci]`
- `f5ff63245cc8ef062c728bd2aa1949cbf717b2e4` — `ci: enforce AETHER LOAD 003 final deployment contract`
- `ba888fc6b550b08b1095b051e209d5a2c0b2e82f` — `fix: align Azure tests with canonical CI runner`

B9 integration scope completed:
- final runtime release advanced to `AETHER-LOAD-003-B9` without changing trading strategy, risk, sizing, fill, or management behavior;
- final cross-module closeout suite composes runtime mode, routing, persistence, risk, sizing, execution-validation isolation, intelligence isolation, and live-order safety;
- all 28 supported asset × horizon routes are evaluated in the zero-signal closeout scenario and all 28 remain rejected with no paper entry;
- deliberately extreme bullish shadow news/community/event context still cannot manufacture a strategy signal or paper order;
- same-asset scalp + swing positions persist through a save/restart cycle with independent route state and originating horizon;
- duplicate same-route position remains blocked after restart;
- closing one restored horizon leaves its sibling horizon intact;
- four 0.75%-risk positions exhaust the 3.00% aggregate portfolio stop-risk ceiling and block a new candidate;
- closing one seeded position restores portfolio risk capacity;
- the previously blocked qualified MCL candidate can enter after capacity is restored, while aggregate risk remains within the ceiling;
- allocator still permits more than four low-risk qualified positions when risk/capital permits;
- legacy LOAD-002 execution-validation position is retired before normal allocation resumes on that tick;
- FX oversized request remains clipped to 100,000 base units / 1.00 standard lot;
- MES oversized request remains clipped to 1 contract;
- equity shares and crypto coin quantities remain free of an incorrect blanket 1.0-unit cap;
- live order placement remains hard blocked even when live flag and test credentials are present;
- B1–B8 focused regression suites remain part of the final full-suite validation, including horizon management and B7 cost reconciliation.

Final deployment contract:
- production worker must report `AETHER-LOAD-003-B9`;
- runtime mode must report `strategy_test`;
- strategy-test mode must be true;
- execution-test mode must be false;
- forced entries must be false;
- worker must be armed, running, and accepting paper entries before deployment verification passes;
- live execution must remain blocked;
- live strategy open stop-risk must not exceed the configured portfolio stop-risk ceiling;
- settings must report 0.75% maximum trade risk and 3.00% maximum portfolio risk;
- fixed strategy position-count governor must remain absent;
- settings must report FX <= 1.00 lot / 100,000 base units and micro futures <= 1 contract;
- equity and crypto quantity units must remain shares / coin quantity;
- community and crypto-calendar intelligence trade influence must remain disabled;
- event policy must remain `observe_only`;
- live orders must remain disabled;
- B8 strategy-vs-validation telemetry and Blotter evidence must remain deployed;
- execution matrix must remain available and report no live-order attempt;
- LOAD-002 experiment endpoint must report the forced experiment inactive and filters normal.

Final validation evidence:
- initial B9 validation candidate `f5ff63245cc8ef062c728bd2aa1949cbf717b2e4`;
- CI run #453 — SUCCESS, 267 passed / 1 warning;
- Azure run #336 build collected the same 267 tests but the `pytest -vv` process stalled after the first app smoke test and hit the existing 5-minute step timeout; deployment was skipped;
- no application assertion failed in Azure #336;
- repair `ba888fc6b550b08b1095b051e209d5a2c0b2e82f` changed only the Azure test invocation from `pytest -vv` to the canonical CI invocation `pytest -q`; no test was removed, skipped, weakened, or altered by the repair;
- CI run #454 — SUCCESS;
- final full suite — 267 passed / 1 warning in 14.45 seconds;
- Azure workflow run #337 — SUCCESS;
- Azure build — SUCCESS with the complete 267-test suite;
- Azure Web App deployment — SUCCESS;
- production runtime verification — SUCCESS;
- post-deploy verifier observed restart convergence: early attempts correctly failed the strengthened armed/running/accepting assertion while the worker was still starting, then the worker reached the complete B9 strategy-test state and verification passed;
- deployed root/static assets report `AETHER-LOAD-003-B9`;
- deployed runtime reports paper strategy test, forced entries OFF, live HARD BLOCKED;
- deployed worker reports armed/running/accepting entries;
- deployed settings report the final B4/B5 risk and sizing contract;
- deployed settings report intelligence trade influence disabled / event policy observe-only;
- deployed Live Trades risk telemetry remains bounded by maximum portfolio risk;
- deployed execution matrix remains isolated and records no live-order attempt;
- deployed LOAD-002 status reports experiment inactive.

Final closeout checklist evidence mapping:
1. STRATEGY TEST / PAPER runtime active — DEPLOYED PROOF;
2. desk armed — DEPLOYED PROOF;
3. live-money execution hard blocked — UNIT + DEPLOYED PROOF;
4. global forced execution-test runtime inactive — UNIT + DEPLOYED PROOF;
5. legacy LOAD-002 positions retired — B9 TICK/RETIREMENT PROOF;
6. zero signal creates zero entry — B9 28-ROUTE PROOF;
7. all supported horizons scheduled/evaluated — B9 28-ROUTE PROOF;
8. multi-horizon same-asset positions work — B9 PERSIST/RESTORE PROOF;
9. duplicate same-route positions blocked — B9 RESTART PROOF;
10. >4 qualified positions possible when risk permits — B9 ALLOCATOR PROOF;
11. aggregate open risk <= configured ceiling — B9 EXHAUST/RECOVER + DEPLOYED PROOF;
12. FX <= 1.00 standard lot — B9 HARD-CAP PROOF;
13. micro futures <= 1 contract — B9 HARD-CAP PROOF;
14. originating horizon survives management and exit — B6 REGRESSION + B9 RESTART PROOF;
15. spread/fees/slippage reconcile into net P&L — B7 REGRESSION IN FINAL 267-TEST SUITE;
16. intelligence cannot manufacture a trade — B9 SHADOW-INTELLIGENCE PROOF + DEPLOYED POLICY;
17. execution validation remains isolated and available — B9 RUNTIME PROOF + DEPLOYED EXECUTION MATRIX;
18. persistence survives restart — B9 SAVE/RESTORE PROOF;
19. CI green — #454 SUCCESS;
20. Azure deploy green — #337 SUCCESS;
21. deployed runtime explicitly reports STRATEGY TEST / PAPER — DEPLOYED PROOF;
22. deployed runtime explicitly reports live blocked — DEPLOYED PROOF.

Safety/invariant evidence:
- no live-money enablement was introduced;
- no setup/gate was weakened to increase trade count;
- no portfolio risk ceiling was loosened;
- no instrument hard ceiling was loosened;
- no horizon-management rule was replaced;
- no B7 cost leg was removed;
- no intelligence source was promoted from shadow observation into a trade creator;
- execution validation remains separate from strategy performance.

### J.A.R.V.I.S. FINAL REVIEW GATE

Review final validated B9 head `ba888fc6b550b08b1095b051e209d5a2c0b2e82f`, the completed checklist above, and this evidence.

If the complete LOAD-003 contract is clear, respond exactly:

`J.A.R.V.I.S. CLOSE — AETHER-LOAD-003 — COMPLETE`

If a B9 or closeout defect exists, respond:

`J.A.R.V.I.S. HOLD — AETHER-LOAD-003 — B9 — <concrete defect/reason>`

ChatGPT must not begin any post-LOAD-003 work before the final J.A.R.V.I.S. close decision.

