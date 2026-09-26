# AETHER vNext — Build Status

**AETHER TRACE:** 2026-09-26 17:54 EDT  
**Branch:** `aether-vnext-swapout`  
**Draft PR:** #12  
**Legacy baseline:** `879736630edf5f41ede90258a4596bf3fff8c053`

## Authority

1. AETHER Firm Master Blueprint v5.0
2. AETHER Playbook Pack v1.4 FULL
3. AETHER Pre-Code Freeze v1.0

Legacy implementation behavior has no design authority over vNext.

## Phase status

### Phase 0 — isolation + freeze loader: COMPLETE

Evidence:
- isolated `backend/aether_vnext/` package;
- static test rejects any `app` / `app.*` import from vNext;
- PAPER ONLY and LIVE BLOCKED contract is asserted in CI;
- frozen source fingerprints, state namespaces, risk defaults, product-side truth,
  crypto-short disablement, ZN execution truth, and allocator-v1 constants are
  encoded;
- PostgreSQL namespace `aether_vnext` is reserved through Alembic revision 0002;
- vNext runtime manifest is configuration-hash bound;
- AETHER vNext CI is green.

### Phase 1 — canonical types: COMPLETE

Implemented:
- MarketObservation;
- Setup;
- Ticket;
- OrderIntent;
- OpenTrade / ClosedTrade;
- ReviewCard;
- GovernorStateRecord;
- PolicySnapshot;
- BrokerAccountLedger;
- EventLedgerRecord;
- typed ExitPlan and precedence;
- deterministic route_id / position_key / signal_key / idempotency_key;
- canonical reason-code vocabulary;
- ProfitabilityEvidence;
- Alpha Factory objects from F-006;
- News-Market Intelligence objects from F-007.

All vNext tests remain isolated from legacy runtime imports.

### Phase 2 — registry + clocks / market truth: COMPLETE

Implemented:
- full canonical Product Registry row contract across the 12 seed assets;
- explicit product-side truth, shortability/locate state, quantity and price physics,
  margin model, fee schedule, calendar identity, lifecycle, execution/data bindings;
- futures continuous-research versus executable-contract separation;
- exact `current_contract`, expiry, next-contract and 48-hour roll-cutoff binding;
- automatic futures roll prohibited;
- binding Part III seed product math for all 12 assets;
- later Part III US10Y/ZN execution truth retained; superseded yield×$1000 execution
  math is not implemented;
- fee/cost calculations for Kraken, tastyfx, Ninja micros and IBKR equities;
- USDJPY quote-cost conversion to USD;
- 5 bps adverse paper slip, spread cost, 1.25 default cost hurdle and strict READY
  inequality;
- equity short borrow charged only to short trades;
- authoritative calendar scheduler interface with DST conversion through
  America/New_York;
- holiday/early-close state supplied by a date-specific calendar provider;
- non-crypto schedules refuse to assume a holiday state when that provider is absent;
- FX rollover maintenance, futures daily maintenance and early-close blocking;
- MarketObservation hard-validity helper with caller-supplied stale threshold;
- completed-bar law using exchange timestamp first, two-second receive grace only
  when exchange timestamp is unavailable, and session-close handling;
- explicit BOUND/UNBOUND data-source state rather than invented provider identities;
- Product Registry, cost, calendar, roll, side-support and anti-invention tests.

Phase 2 completion evidence:
- AETHER vNext CI run #44: SUCCESS.
- 53 isolated vNext tests passed.
- repository-wide CI was checked separately and remains red only on the five known
  unchanged legacy sleeve/portfolio tests tracked as AETH-VN-001.
- AETH-VN-002 records the intentional external source/calendar/contract binding
  dependency that blocks FIRE until later adapter phases bind it.


### Phase 3 — Firm book + persistence projections: COMPLETE

Implemented:
- isolated Alembic revision 0003 under PostgreSQL schema `aether_vnext`;
- migration pinned to frozen `schema_v0003` metadata so later runtime schema
  evolution cannot silently change historical migration behavior;
- durable Product Registry state, MarketObservation, PolicySnapshot, Governor state,
  broker-account ledgers, Setup, Ticket, ExitPlan, OrderIntent, OpenTrade,
  ClosedTrade, ReviewCard and EventLedger tables;
- universal `decision_lineage` projection with firm_event_id, setup/ticket/order/trade
  IDs, asset/route, policy/config hash, market observation and first-killer fields;
- current `route_review_state` projection so KEEP/BENCH/operational state survives
  restart independently of historical ReviewCards;
- one-active-position-per-`asset:horizon` DB constraint through
  `active_positions.position_key`;
- unique ticket `signal_key`, unique OrderIntent `idempotency_key`, durable
  `signal_consumptions`, and general mutation-idempotency table;
- append-only EventLedger DB trigger;
- immutable PolicySnapshot, ExitPlan, ClosedTrade and signal-consumption triggers;
- four broker-local ledgers seeded once by migration at $4k/$2k/$2k/$2k;
- provisioning guard proving restart cannot re-seed/mint paper capital;
- broker ledger and Governor optimistic row versions;
- ledger-transfer and reconciliation-run persistence contracts;
- read-only restart snapshot for registry, policies, Governor, ledgers, in-flight
  pipeline state, active positions, open admission records, ExitPlans, Review state,
  consumed signals, idempotency and reconciliation history;
- no reference to legacy `aether_runtime_state`.

Phase 3 completion evidence:
- AETHER vNext CI run #78: SUCCESS.
- 70 isolated vNext tests passed.
- repository-wide CI run #505 was checked: 360 passed / 5 failed.
- the five failures are the same unchanged legacy `test_sleeve_portfolio.py`
  failures tracked as AETH-VN-001; no new vNext failure appeared.

### Phase 4 — Trading Clock + market-data pipeline: COMPLETE

Implemented:
- provider-neutral quote adapter boundary plus separate MarketPrint adapter contract;
- concrete Kraken public ticker parser for BTC/ETH only, with unsupported symbols ignored;
- canonical MarketObservation normalization;
- source-aware primary/fallback selection that filters by asset before provider precedence;
- future market timestamps rejected rather than clamped into false freshness;
- freshness, crossed-book and invalid-book refusal;
- calendar/session eligibility included in the non-bypassable market-validity gate;
- closed-session observations are still preserved for truth/audit, but cannot become executable;
- MarketObservation persistence by durable observation_id;
- exchange-timestamp bar bucketing in venue timezone;
- completed-bar construction with no synthetic missing bars;
- authoritative session/early-close final-bar timestamps;
- out-of-order print rejection;
- shared bar-builder semantics for replay and paper;
- completed-bar Trading Clock keyed by explicit playbook trigger interval rather than
  an invented universal horizon cadence;
- one evaluation per consumed completed trigger bar;
- unsupported/inactive/session-closed/forming/wrong-interval routes are not due;
- unknown non-Kraken market-data bindings and stale thresholds remain explicitly
  unbound under AETH-VN-002 rather than guessed.

Phase 4 completion evidence:
- AETHER vNext CI run #122: SUCCESS.
- **87 isolated vNext tests passed.**
- repository-wide CI run #527: SUCCESS.
- **382 repository tests passed, 1 warning.**
- PR remains DRAFT; PAPER ONLY / LIVE HARD BLOCKED remained intact.

### Phase 5 — Execution Engine: COMPLETE

Implemented:
- two-phase READY → RESERVED → SUBMITTED → FILLED / REJECTED / CANCELLED_STALE lifecycle;
- broker-local Phase-A cash/margin reserve committed before any adapter wait;
- persisted MarketObservation required at reserve and re-read at fill;
- source-owned reserve formulas for Kraken spot, tastyfx FX, Ninja futures and IBKR equities;
- canonical paper-sleeve routing per asset; no cross-sleeve borrowing;
- binding OPEN idempotency key `sha256(ticket_id|side|qty|asset|horizon|signal_key)`;
- signal_key remains unconsumed until successful OPEN;
- one active `asset:horizon` occupancy enforced through the durable book;
- 250 ms paper fill latency and 15-second durable submit timeout;
- 2-second stale-intent reconciler with terminal-state-wins late-fill behavior;
- all-or-none seed-twelve fills; paper PARTIAL remains disabled rather than invented;
- healthy/fresh market requirement, spread-doubling entry guard and conservative bid/ask fills;
- 5 bps adverse paper slip on entry and exit;
- protective stop gap-through exit pricing rather than perfect-stop fills;
- explicit AETH-VN-004 erratum for the contradictory `bad_fill_through_stop` inequality;
- frozen ExitPlan identity from READY through OPEN;
- transactional OPEN creation, signal consumption, active-position claim and EventLedger write;
- transactional FLATTEN_REQUEST → close OrderIntent → FILLED → FLAT lifecycle;
- OPEN reserve/margin retained through the trade and released exactly once at FLAT;
- normalized spot/equity-long inventory keyed by `(broker_account_id, asset_id)`;
- BTC/ETH inventory isolation inside Kraken and no cash-inventory rows for futures/FX;
- self-contained ClosedTrade execution evidence including entry/exit identity, prices, costs,
  duration, MFE/MAE, capture and exit reason;
- product-correct gross-P&L math for crypto/equity, FX, micro futures and US10Y/ZN execution;
- zero-fill OPEN failure releases reserve without consuming signal and preserves
  `first_killed_by` / `first_kill_reason`;
- failed CLOSE attempts leave the successful OPEN lineage and position intact;
- exact v4.2.1 OrderIntent vocabulary under schema revision 0010:
  `symbol_executed`, `requested_qty`, `expected_fill_price`, `slip_usd`,
  `slip_bps`, `observation_id_at_reserve`, `observation_id_at_fill`, `version`,
  with `order_type=MARKET_PAPER`;
- PAPER ONLY / LIVE HARD BLOCKED remains non-bypassable.

Phase 5 completion evidence:
- AETHER vNext CI run #338: SUCCESS — **160 isolated vNext tests passed**.
- repository-wide CI run #647: SUCCESS — **455 tests passed, 1 warning**.
- PR #12 remains DRAFT and mergeable.
- production `main` remains untouched.
- no strategy/playbook conversion, forward evidence, or live authorization was introduced.

Phase-boundary handoff:
- AETH-VN-007 was carried into Phase 6 as a blocking accounting gate and is now CLOSED.
- Phase 5 execution semantics remain unchanged; Phase 6 consumes a conservative,
  non-double-counted Firm-equity denominator.


### Phase 6 — Risk + Governor: COMPLETE

Implemented:
- conservative sleeve-equity projection that removes spot/equity-long purchase backing
  reserve once before adding marked inventory, closing AETH-VN-007;
- consolidated Firm equity from the durable broker-local book;
- constitutional stop-risk ceilings fixed at trade 0.75%, asset 1.50%, cluster 2.25%,
  and portfolio 3.00% of Firm equity;
- product-correct stop-loss economics and quantity-step floor-down before final
  dollar-risk verification;
- product/broker/capital quantity caps can only reduce Risk-derived size;
- active-book stop-risk recomputed from actual entry plus frozen hard stop and checked
  against persisted initial stop-risk;
- deterministic asset / cluster / portfolio exposure aggregation;
- atomic Phase-A admission through a durable Firm risk-admission guard;
- RESERVED and SUBMITTED OPEN intents consume persistent pending stop-risk so concurrent
  candidates cannot spend the same capacity;
- schema revision 0011 adds the Firm admission guard and durable pending-risk records;
- pending stop-risk transitions atomically to OpenTrade risk on FILLED and is released
  on zero-fill terminal outcomes;
- restart snapshots preserve the admission guard, pending risk, Governor state, and
  deterministic reconciliation findings without recreating missing safety state;
- reconciliation detects missing/orphaned/nonpending/mismatched risk-reservation state;
- durable Governor NORMAL/HALT state enforced ahead of new Risk admission;
- route, venue, product and desk HALTs are supported; product HALT uses the existing
  canonical lifecycle_ineligible reason rather than inventing product_halted;
- authenticated operator-reset contract, audit EventLedger entry, and optimistic
  Governor row-version protection;
- Review BENCH remains separate from Governor HALT;
- public OPEN reservation now has one checked path:
  reserve_risk_checked_open_intent; the lower-level reservation primitive is private
  and statically forbidden from other vNext runtime modules;
- risk-reducing FLATTEN remains outside the OPEN-admission veto path;
- PAPER ONLY / LIVE HARD BLOCKED remains non-bypassable.

Phase 6 completion evidence:
- implementation head before documentation closeout:
  `5a151572a9665f3848811fee81a9d3e11f32649c`;
- AETHER vNext CI run #354: SUCCESS — **212 isolated vNext tests passed**;
- repository-wide CI run #663: SUCCESS — **507 tests passed, 2 warnings**;
- no live authorization, strategy/playbook conversion, or legacy runtime import was introduced.

Contained source-policy dependencies carried forward:
- AETH-VN-008: the exact canonical seed-12 cluster assignment is not present in the
  frozen source. Risk requires explicit cluster identity and fails closed rather than
  importing the historical legacy map.
- AETH-VN-009: the Master requires a versioned daily-loss HALT threshold but supplies
  no binding numeric value. Governor HALT enforcement is complete; automatic
  daily-loss triggering remains unbound until an approved Policy Book value exists.


### Phase 7 — Playbook Runtime: COMPLETE

Implemented:
- exact bound 27-playbook registry: 26 CANDIDATE definitions + 1 BENCH;
- Family counts frozen at A=16, B=9, C=2;
- exact trigger interval per playbook rather than deriving cadence from horizon;
- operational disablement remains separate from evidence state;
- BTC/ETH failed-break short definitions remain preserved but DISABLED under current
  long-only Kraken spot product truth;
- shared closed-bar / PIT runtime law and traceable disposition vocabulary;
- volatility bands frozen at Family A/B [40,85] inclusive and Family C <40;
- same-bar Family A -> B -> C precedence;
- deterministic Family-A breakout/session/prior-day structure evaluation;
- deterministic ETH rider dependency gating without merging its evidence with standalone
  ETH behavior;
- deterministic Family-B failed-break state machine with exact fail windows;
- Family-B existing-position silence and equity-short locate requirement;
- deterministic Family-C EURUSD/NVDA range-harvest structure;
- source-bound playbook stop/target/time-stop metadata, including valid ZN 1/64 stop
  tick alignment;
- explicit fail-closed exposure of source-incomplete exit fields rather than invented
  parameters;
- integrated closed-bar Playbook Runtime that may identify WATCH-eligible candidates
  but cannot create Setup/Ticket records or impersonate Clerk, Risk, Governor, or
  Execution;
- canonical seed-12 Risk cluster binding:
  BTC/ETH=crypto, EURUSD/USDJPY=fx, MES/MNQ/NVDA/TSLA/PLTR=us_beta,
  MGC=metal, MCL=energy, US10Y=rates;
- source-bound ETH cross-asset Risk hitch metadata:
  pb_eth_rider_v1_2 and pb_eth_failed_break_v1_3 attribute 50% of ETH initial stop-risk
  to the BTC asset cap;
- no legacy app.* strategy imports.

Phase 7 completion evidence:
- implementation head before documentation closeout:
  `706ce779928d8000e9ed003e443cb5d895333512`;
- AETHER vNext CI run #363: SUCCESS — **330 isolated vNext tests passed**;
- repository-wide CI run #672: SUCCESS — **625 tests passed, 1 warning**;
- PAPER ONLY / LIVE HARD BLOCKED remains non-bypassable.

Issue transitions at Phase 7 closeout:
- AETH-VN-008: CLOSED — canonical cluster mapping is now source-bound.
- AETH-VN-010: CONTAINED — ETH rider exit fields and Family-C stop anchor are
  source-incomplete; affected routes may WATCH but may not advance to a ticket requiring
  a complete ExitPlan until resolved.
- AETH-VN-011: CONTAINED — ETH 50% BTC asset-cap hitch is source-bound in metadata but
  must be durably carried through Setup -> Risk admission -> restart before those
  playbooks can create tickets.


### Phase 8 — Scout / Sniper / Allocator / Risk / Clerk: COMPLETE

Implemented:
- revision 0012 durable Scout WATCH lineage with immutable playbook_id/playbook_version,
  canonical risk_cluster_id, asset-risk hitch metadata, trigger-bar close timestamp,
  and exit-contract completeness;
- one Scout evaluation per playbook/asset/horizon/side/completed trigger bar;
- Sniper completed-bar-only WATCH -> FIRE contract with exact deterministic signal_key,
  grain revalidation, invalidation/staleness/product-side/legal-stop checks, and
  duplicate-signal rejection;
- deterministic F-005 FIRE allocator sequencing with frozen 45/20/15/10/10 weights,
  evidence/diversification/execution-quality scoring, correlation hard block, and
  deterministic tie-break chain; allocator has no sizing or reservation authority;
- cost-aware Risk sizing: per-unit modeled loss = stop-loss economics + estimated
  round-trip execution cost;
- cross-asset Risk hitch caps applied before quantity is accepted;
- FIRE -> SIZE persistence with durable playbook identity and no Clerk authority;
- ETH -> BTC 50% hitch persists as BTC asset-cap occupancy while pending and OPEN,
  does not double-count cluster/portfolio risk, survives restart reconstruction,
  and fails closed on reconciliation drift;
- Clerk source-bound opportunity geometry and exact product cost model;
- strict cost-edge hurdle, source-bound product/shortability/locate checks, and
  SIZE -> READY / REJECTED transition;
- Clerk never changes Risk-derived quantity;
- incomplete ExitPlan definitions under AETH-VN-010 are allowed to WATCH but remain
  blocked from executable ticket progression;
- PAPER ONLY / LIVE HARD BLOCKED remains intact.

Phase 8 completion evidence:
- implementation head before documentation closeout:
  `58338b3c55d216a80e3c93cc65ea49664751103c`;
- AETHER vNext CI #373: SUCCESS — **392 isolated vNext tests passed**;
- repository-wide CI #682 clean rerun: SUCCESS — **687 tests passed, 1 warning**;
- the first repository #682 attempt timed out in legacy TestClient smoke teardown
  with exit 124 and no assertion failure; the single rerun completed green.

Issue transitions at Phase 8 closeout:
- AETH-VN-010: remains CONTAINED — three source-incomplete ExitPlan contracts stay
  fail-closed before executable ticket progression.
- AETH-VN-011: CLOSED — ETH cross-asset Risk hitch is now durable through pending,
  OPEN, restart reconstruction, reconciliation, and release semantics.
- AETH-VN-012: CONTAINED / NON-BLOCKING — F-005 says percentile rank but does not
  specify ties/singletons; vNext uses an explicit deterministic average-rank
  normalization until current authority binds a different convention.




### Phase 9 — Profitability Evidence / Review: IMPLEMENTATION COMPLETE

Status distinction:
- **Part-IV P1–P11 implementation is complete.**
- **Empirical P11 burn-in is not complete merely because the code exists.**
- **Aether profitability_ready has NOT been established from real sustained forward-paper/OOS evidence.**
- PAPER ONLY / LIVE HARD BLOCKED remains unchanged.

Implemented:
- P1 immutable ProfitabilityEvidence plus ReviewCard persistence and deterministic
  promotion/demotion gates;
- P2 durable F-006 research-integrity ledger for hypotheses, append-only annotations,
  PIT dataset snapshots, parameterized experiments, backtest runs, chronological folds,
  and failed/retired candidate retention;
- P3 candidate/baseline benchmark evidence on the same economic path with explicit
  base/+25%/+50% cost stress;
- P4 point-in-time six-family regime tagging persisted from Setup through ClosedTrade;
- P5 intended-size capacity evidence covering marginal slippage, spread readiness,
  depth/product capacity, locate/borrow, carry, and gap/tail cost; KEEP_TRUSTED now
  fails closed unless persisted capacity evidence is ready;
- P6 portfolio contribution diagnostics for realized co-loss, simultaneous stop-risk
  stress, marginal expected-return/stop-risk/drawdown contribution, broker-local
  capital fragmentation, and explicit same-bet overlap;
- P7 direct path diagnostics for max drawdown, losing streak, recovery duration, tail
  loss versus initial stop-risk, and explicit unbound status for source-unspecified
  resampling parameters;
- P8 rolling/reference decay evidence with immutable automatic Review queueing and no
  automatic strategy mutation;
- P9 configuration-isolated Scout/Sniper/Clerk traffic experiments, WAIT/DEFER
  separation, first-killer diagnostics, and shadow prior-policy comparison that can
  never create orders;
- P10 read-only profitability operator projection covering Firm strip, route board,
  traffic funnel, execution panel, Review panel, and model-risk panel without seat,
  Risk, Governor, or execution authority;
- P11 immutable Firm-level burn-in/profitability-readiness assessment with actual
  burn-in window, route counts, defect gates, held-out/net-cost/execution/regime/Risk/
  portfolio completeness, decay-to-BENCH capability, lineage integrity, full-history
  retention, and a hard invariant that profitability readiness cannot authorize live.

Phase 9 implementation evidence:
- P1 persistence: `adc995c848ca3a915ab8f12d2aa51120973ca58f`;
- P2/P11-supporting research ledger: `0bdcfff6ef94472346f075a938ef1ad3a2b61e9c`;
- deterministic Review gates: `96d6a2d87ce09aa793f7c08443c95adf589363ae`;
- EvidenceWindow/sample-domain isolation: `52cb10460eb1cf0a053ad342cc64ed8bc05c9d4a`;
- benchmark/cost stress: `01fac4853826388fb48a0377d7cd881ca73a1831`;
- portfolio/concentration/path diagnostics: `931b4bcba1791a02814d54b476add4c66ca34225`;
- PIT regime lineage: `7798a8f663bcfa3d5338786242d3007b8a669341`;
- decay Review queue: `568080b1dc2fe366019e0b71241d7d2985751773`;
- intended-size capacity gate: `4a3c9618ed91f143994fcef4ecba033540b9a531`;
- traffic/config isolation: `853df7af487ac72b4572aa5a5600c298e5586937`;
- P10 operator projection: `a63131c661c8cd91aa9f48afb26254fca2b5b657`;
- P10 projection fix: `fa3fc7e26d430b2aadae0871a040f1ebc988bd96`;
- P11 readiness gate: `b6d9b22bb369d96ec505baf43180ae8287022307`.

Latest verified implementation CI:
- P10 fix — repository CI #695: SUCCESS;
- P10 fix — AETHER vNext CI #386: SUCCESS;
- P11 — repository CI #696: SUCCESS;
- P11 — AETHER vNext CI #387: SUCCESS.

Contained source/policy dependencies carried forward:
- AETH-VN-009 — numeric daily-loss Governor trigger remains unbound;
- AETH-VN-010 — three source-incomplete ExitPlan contracts remain fail-closed;
- AETH-VN-012 — Allocator percentile tie convention is explicit but not source-bound;
- AETH-VN-013 — universal benchmark "not worse" scalar comparator is not source-bound;
- AETH-VN-014 — resampled-path parameters and universal concentration normalization
  are not source-bound;
- AETH-VN-015 — decay materiality thresholds/window sizes require versioned policy;
- AETH-VN-016 — capacity readiness thresholds are route/product policy inputs;
- AETH-VN-017 — traffic-experiment drawdown/cost/cluster deterioration tolerances
  require explicit evidence;
- AETH-VN-018 — burn-in duration and OOS/trusted-route sufficiency thresholds require
  versioned policy decisions.

P11 operational gate still pending:
- actual sustained forward-paper operation;
- no unresolved accounting/model defects during that burn-in;
- sufficient clean OOS/trusted-route evidence under an approved sufficiency policy;
- a real Firm snapshot that satisfies the P11 readiness assessment.

No synthetic duration, fake trusted-route count, fabricated OOS evidence, or paper
equity-curve shortcut may set profitability_ready=true.


## CI state

### vNext CI

GREEN on the current replacement code path.

### Repository-wide CI

GREEN on the current replacement branch. AETH-VN-001 is CLOSED. Superseded workflow
pileups are cancelled automatically and both workflows have a 10-minute timeout.

## Current safety

- production `main` is untouched by vNext;
- no vNext production deployment;
- no live orders;
- no forced strategy entries;
- Phase 9 Part-IV implementation is complete on the replacement branch;
- P11 empirical burn-in / profitability readiness is NOT yet established;
- no live authorization or production cutover;
- no legacy evidence imported into vNext;
- PR #12 remains DRAFT.

## Next build target

Forward-paper burn-in + cutover readiness.

Immediate gates:
- run natural PAPER setups with forced strategy entries OFF;
- accumulate clean paper-forward/OOS evidence without mixing execution-validation,
  historical/in-sample, or future-live domains;
- exercise the P11 profitability-readiness assessment against real Firm snapshots;
- keep profitability_ready=false until approved sustained-operation and OOS/trusted-route
  sufficiency policies are actually satisfied;
- resolve or explicitly continue to contain AETH-VN-009/010/012–018;
- complete operator UI integration against the read-only P10 projection;
- preserve PAPER ONLY / LIVE HARD BLOCKED throughout burn-in.

Only after those evidence/cutover gates pass may the project evaluate a separate,
explicitly authorized live-readiness phase. Phase 9 does not grant live authority.
