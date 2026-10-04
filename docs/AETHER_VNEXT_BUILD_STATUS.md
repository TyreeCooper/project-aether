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

## Historical next-build checkpoint — SUPERSEDED

This checkpoint predates the verified burn-in environment and is retained only as
historical implementation context. The canonical current state is the Monitor
Reconciliation Checkpoint at the end of this document.

Immediate gates:
- satisfy AETH-VN-020 by configuring a dedicated non-production vNext PostgreSQL book
  and GitHub Environment `aether-vnext-burnin`;
- dispatch the existing AETHER vNext CI workflow against `aether-vnext-swapout`;
- require the target-database isolation guard to pass before migrations;
- initialize only schema 0001–0020 plus the canonical policy snapshot;
- inspect the uploaded full-universe burn-in preflight artifact;
- if any route is missing held-out evidence, fill only that real evidence gap;
- start campaign #1 only after the canonical preflight returns `startable=true`;
- then run natural PAPER setups with forced strategy entries OFF;
- accumulate clean paper-forward/OOS evidence without mixing execution-validation,
  historical/in-sample, or future-live domains;
- exercise P11 against real Firm snapshots;
- keep profitability_ready=false until approved sustained-operation and OOS/trusted-route
  sufficiency policies are actually satisfied;
- preserve PAPER ONLY / LIVE HARD BLOCKED throughout burn-in.

Only after those evidence/cutover gates pass may the project evaluate a separate,
explicitly authorized live-readiness phase. Phase 9 does not grant live authority.


### Historical forward-paper burn-in checkpoint — SUPERSEDED

Status distinction:
- repository-side burn-in controls are implemented and CI-verified;
- no real vNext burn-in database/environment has been configured yet;
- no real canonical burn-in preflight has been executed against a deployed vNext book;
- campaign #1 has NOT started;
- empirical profitability readiness remains unproven.

Implemented after Phase 9:
- schema revision 0020 immutable forward-paper campaign, route-baseline, and
  campaign-window ledger;
- campaign-aware paper_forward EvidenceWindow persistence only;
- canonical ClosedTrade -> DecisionLineage -> Setup verification for paper-forward
  evidence;
- current held-out baseline freezing with deterministic route/campaign hashes;
- read-only campaign preflight with exact blocker codes and independent held-out n;
- campaign start consumes the same preflight result used by the operator/control plane;
- dedicated vNext-only PostgreSQL configuration namespace using AETHER_VNEXT_*;
- no fallback to legacy DATABASE_URL or AZURE_POSTGRESQL_CONNECTIONSTRING;
- async Alembic support for PostgreSQL/asyncpg;
- canonical policy snapshot bootstrap only; no trade/evidence/capital seeding;
- same-repository PR-label burn-in bridge through the dedicated burn-in workflow;
- exact PR head SHA checkout plus environment-secret approval boundary;
- canonical WATCH coverage manifest separated from the statically executable
  campaign universe, with source-incomplete exclusions retained visibly;
- canonical executable-universe preflight/start only; operator-supplied route
  subsets are not accepted;
- durable JSON preflight artifacts on both startable and non-startable runs;
- read-only target-database isolation guard that refuses known legacy Aether public
  tables before any vNext migration is applied.

Burn-in control-plane implementation commits:
- campaign ledger / schema 0020: `a7b864080753295e97f6da28c4e7d7eb4718e7fe`;
- evidence-domain test correction: `a86fdbc91aaaefe65f38c88fa4b6fad801dc047b`;
- canonical held-out campaign start: `f1470084320c628823b6d9ad687810dbf0af4505`;
- read-only canonical preflight: `2b171c93db75fd5bd9dea7542e5cc720afa5033d`;
- preflight diagnostic test alignment: `b842af49bcef8ec62f2ea12759839adca687c273`;
- isolated non-production DB control plane: `ebf319fee487724a36063ab542a89d56cc62271c`;
- durable preflight artifacts: `17076f0849a09b73f9b21db479390e350784bf1a`;
- pre-merge canonical dispatch bridge: `4e79016fc519b93de60b558aa0cc87f0dad0c840`;
- legacy target-database rejection: `a8a554985107aad2b352bea13ea987a9d15a9ad2`.

Latest verified CI:
- AETHER vNext CI #403: SUCCESS;
- repository CI #712: SUCCESS.

External gate before campaign #1:
- provision or identify a dedicated non-production PostgreSQL database for vNext;
- create/configure GitHub Environment `aether-vnext-burnin`;
- configure exactly one dedicated vNext database connection path;
- configure environment protection/review for `aether-vnext-burnin` before any
  secret-bearing run;
- on PR #12, apply label `aether-vnext-burnin-preflight-approved` to run the
  same-repository/head-SHA-gated initialization + canonical preflight bridge;
- inspect the uploaded canonical preflight JSON;
- only after `startable=true`, apply label `aether-vnext-burnin-start-approved`
  to re-preflight and atomically create campaign #1.

AETH-VN-020 tracks this external environment dependency. It blocks real burn-in
execution but does not change PAPER ONLY / LIVE HARD BLOCKED.


### Burn-in hardening correction — provenance, canonical execution, trusted dispatch

The earlier statement that repository-side burn-in was fully closed was too broad.
Three gaps were subsequently corrected:

- schema 0021 binds HELD_OUT campaign baselines to immutable BacktestRun,
  ResearchDatasetSnapshot, and FoldResult provenance;
- canonical WATCH coverage remains visible, while Campaign #1 derives only the
  source-complete executable subset and does not accept a caller-selected subset;
- pre-merge secret-bearing burn-in is triggered only by explicit approval labels on
  the same-repository `aether-vnext-swapout` PR head and remains subject to the
  `aether-vnext-burnin` environment boundary.

These controls do not create historical evidence, market-data bindings, broker
readiness, or profitability. Real preflight and Campaign #1 remain externally gated.

### Runtime Product Registry burn-in gate — IMPLEMENTED

Additional hardening after the trusted-dispatch bridge:

- schema revision 0022 freezes a runtime Product Registry binding hash on every
  forward-paper campaign route;
- reviewed external binding truth is persisted in `product_registry_state`;
- campaign preflight now requires durable broker-symbol, market-source, stale-threshold,
  calendar-provider, futures-lifecycle, and locate-provider facts where applicable;
- futures broker symbol/current-contract drift and the 48-hour roll cutoff fail closed;
- Campaign #1 cannot start from a transient or caller-only binding;
- initialization can apply `AETHER_VNEXT_RUNTIME_BINDINGS_JSON` and emits a durable
  binding report before canonical preflight;
- no numeric stale thresholds, current futures contracts, expiries, provider IDs, or
  locate sources were invented.

Implementation:
- `e94440563fdf2d02a270d73bddf49ddbc7955a26` —
  `feat(vnext-registry): gate burn-in on durable runtime bindings`;
- `a3666c7beeb8ccf8615fab80b4dbb18d716438c6` —
  pytest helper collection correction.

The binding manifest proves reviewed identity/lifecycle configuration only. It does
not prove live provider connectivity, current quote health, holiday-feed health, or
profitability. Those remain runtime/empirical gates.


## Post-Phase-9 integration checkpoint — 2026-09-27

This section supersedes older "next build target" wording above where later work has
already closed the repository-side gaps.

Current verified implementation head before this documentation closeout:

`255225e4f6e01633c91065f55e70f0582cb4ff67`

Verified CI at that head:

- AETHER vNext CI #421 — SUCCESS;
- repository CI #730 — SUCCESS.

Repository-side integration now includes:

- durable runtime Product Registry bindings with campaign-route binding hashes;
- provider-neutral market ingress and immutable ingress-attempt evidence;
- Kraken BTC/ETH public WebSocket v2 market-data path;
- TradingHours-backed exchange-calendar snapshot provider;
- explicit FX OTC 24x5/weekend + rollover calendar semantics;
- IBKR equity top-of-book transport and operator-local ingress probe;
- immutable IBKR equity shortability evidence with exact evidence lineage on admitted
  short OrderIntents;
- NinjaTrader DEMO futures market-data transport and canonical ingress probe;
- provider-neutral FIX 5.0 SP2/FIXT 1.1 market-data application layer;
- tastyfx FIX source identity retained as fail-closed `provider_spec_pending`;
- exact seed-12 runtime-manifest enforcement;
- atomic strict manifest validation before any runtime-registry mutation;
- read-only burn-in readiness audit covering database isolation, schema completeness,
  seed-12 binding coverage, canonical preflight state, and blocker classification.

### Current real-burn-in gates — superseded by monitor reconciliation below

The provider abstraction statements remain historical implementation context. The
dedicated burn-in PostgreSQL target and protected GitHub Environment were subsequently
verified and AETH-VN-020 was closed. Use the Monitor Reconciliation Checkpoint below
for current blockers.

The protected readiness action is:

`aether-vnext-burnin-readiness-approved`

It is read-only and must not be confused with initialization or campaign start.

## Monitor Reconciliation Checkpoint — 2026-09-27 23:13 EDT

**Authority:** this is the canonical current-status block for the replacement branch.
It supersedes older "current", "next build", environment, and CI wording above when
those statements conflict with this checkpoint.

### Verified repository-state evidence

This block is a checkpoint record, not a live branch pointer. The current branch HEAD,
PR state, and CI conclusions MUST be read from GitHub by the monitor at transition
time. Do not create recursive documentation commits merely to chase the checkpoint
file's own SHA.

Checkpoint evidence immediately before this status freeze:

- branch: `aether-vnext-swapout`;
- PR #12: OPEN, DRAFT, mergeable;
- implementation head before the checkpoint-only status commit:
  `499b496459223867eff20c49b46dac8b8a100c29`;
- implementation commit:
  `fix(vnext-burnin): gate artifacts on producer steps`;
- AETHER vNext CI #535: SUCCESS;
- repository CI #844: SUCCESS;
- this checkpoint's own commit and later commits are validated by the live monitor,
  not by rewriting this block after every successful commit;
- production `main` remains outside this vNext replacement work;
- PAPER ONLY / LIVE HARD BLOCKED remains unchanged.

### Verified burn-in environment state

AETH-VN-020 is CLOSED.

The protected GitHub Environment `aether-vnext-burnin` is operational. The
dedicated PostgreSQL target `aether_vnext_burnin` was reached successfully, database
isolation passed, and the legacy-table scan returned none. The approved initialization
run applied the then-current vNext migrations and bootstrapped the canonical policy
snapshot.

Burn-in Control Plane run #4 verified the external database at the reconciled
branch head and successfully applied migration `0024 -> 0025` before stopping at
the separately tracked runtime-binding gate. The canonical policy snapshot was also
confirmed present. External burn-in database schema revision 0025 is therefore
verified applied.

### Latest protected burn-in execution

Burn-in Control Plane run #4 executed against the reconciled branch head. Verified
results:

- database isolation: PASS;
- legacy Aether public-table scan: PASS / none found;
- schema migration `0024 -> 0025`: SUCCESS;
- canonical policy snapshot: present;
- runtime Product Registry binding step: FAIL-CLOSED because
  `AETHER_VNEXT_RUNTIME_BINDINGS_JSON` is not configured;
- canonical preflight: not executed because initialization stopped at the binding gate;
- Campaign #1: not started.

The subsequent workflow hardening commit gates artifact publication on the producing
step outcome so skipped upstream work cannot create a second misleading missing-
artifact failure.

### Current open external/runtime gates

AETH-VN-021 remains OPEN. The exact seed-12
`AETHER_VNEXT_RUNTIME_BINDINGS_JSON` has not been supplied. No guessed stale
thresholds, futures lifecycle values, provider IDs, calendar identities, broker
symbols, or equity locate sources may be substituted.

AETH-VN-022 remains OPEN and is deliberately deferred until the end by operator
instruction. The private tastyfx FIX/session specification and reviewed EURUSD/USDJPY
provider contract remain unavailable. Deferral does not change the blocker and does
not authorize a partial manifest to masquerade as canonical completion.

### Current held-out research state

Repository implementation now includes:

- operator-approved AETHER Indicator Convention v1 for deterministic EMA20/EMA50,
  ATR14, and non-annualized RV14;
- operator-approved Volatility Percentile Convention v1 using PIT empirical midrank
  against the prior 90 calendar days of the same interval;
- canonical no-cherry-pick HELD_OUT replay planning for all 74 executable
  route/playbook pairs;
- real-input requirements for PIT dataset identity, exact code SHA, chronological
  non-overlapping folds, and full canonical asset coverage;
- immutable PIT research-bar warehouse schema revision 0025 with content-addressed
  dataset identity and anti-hindsight availability timestamps;
- strict canonical HELD_OUT import requiring preloaded immutable research bars;
- Kraken BTC/ETH historical OHLCVT parsing that preserves missing intervals rather
  than synthesizing candles;
- IBKR NVDA/TSLA/PLTR historical request/response boundary that preserves provider
  timestamps without inventing bar-open/bar-close semantics;
- NinjaTrader/Tradovate MES/MNQ/MGC/MCL/US10Y historical chart boundary that preserves
  provider timestamps and contract identity without inventing bucket semantics;
- deterministic completed-bar replay feature kernel;
- regime-ready replay feature snapshots with the source-bound 90-day volatility band;
- replay adapters into the frozen Family A/B/C evaluators with unresolved higher-
  timeframe, dependency, locate, counter-trend, and range facts kept explicit;
- deterministic closed-bar replay orchestration through the existing A->B->C
  same-bar precedence engine;
- point-in-time failed-break episode reconstruction for Family-B replay;
- exact route x fold replay-result coverage with missing, unexpected, duplicate,
  identity-drift, and replay-hash checks;
- canonical held-out FoldResult assembly from reviewed real trade outcomes using the
  existing AETHER profitability metrics engine;
- canonical HELD_OUT EvidenceWindow assembly with non-overlapping folds, immutable
  trade identity, and deterministic metrics snapshot hashes;
- canonical HELD_OUT research-manifest assembly through the existing strict manifest
  validator;
- read-only HELD_OUT closeout readiness aggregation for canonical-route coverage,
  replay-result coverage, fold/window presence, and preserved external blockers;
- read-only operator closeout CLI consuming reviewed manifest, replay plan, and replay
  result artifacts without opening the database or starting a campaign.

Latest verified implementation head before this checkpoint-only documentation commit:
`951eb3cc4ad1de87e83898e65640660be6531025`
(`test(vnext-research): align closeout CLI duplicate assertion`), with AETHER vNext
CI #559 and repository CI #868 successful.

Repository-side HELD_OUT closeout tooling is now built through the final read-only
audit boundary. This does NOT establish empirical Phase 18 completion.

Remaining hard/external or empirical work:

- import a reviewed real canonical PIT research dataset; no synthetic history is
  permitted;
- resolve source-bound provider timestamp semantics before IBKR/NinjaTrader raw
  historical timestamps may be normalized into immutable research bars;
- provide the exact seed-12 runtime Product Registry binding manifest
  (`AETHER_VNEXT_RUNTIME_BINDINGS_JSON`);
- finish the deliberately deferred private tastyfx FIX/session contract for
  EURUSD/USDJPY rather than substituting guessed provider facts;
- execute the real canonical route x fold HELD_OUT replay and produce reviewed trade
  outcomes, FoldResults, EvidenceWindows, and one full-universe manifest;
- run the strict closeout audit against those real artifacts and require
  `ready=true`;
- only after the canonical burn-in preflight is startable may Campaign #1 begin;
- accumulate real paper-forward/OOS evidence with forced entries OFF.

Phase 18 therefore remains empirically OPEN even though the repository-side closeout
pipeline is substantially complete. Historical replay results or forward-paper
evidence must not be fabricated to close this gap.

### Current campaign state

- Campaign #1: NOT STARTED;
- canonical preflight `startable=true`: NOT ESTABLISHED;
- canonical full-route HELD_OUT provenance: NOT ESTABLISHED;
- P11 empirical profitability readiness: NOT ESTABLISHED;
- live authorization: NONE.

### Monitor discipline

Every subsequent transition must use:

`MONITOR -> RECONCILE -> ACT -> VALIDATE -> FREEZE -> MONITOR AGAIN`

Before selecting a module, editing code, committing, dispatching a protected workflow,
or interpreting a frozen state, verify the live branch head, PR state, both CI lanes,
and the latest canonical project-fact checkpoint. Any substantive mismatch is a hard
stop until reconciled. A checkpoint file being one commit behind because that commit
only froze the checkpoint itself is not substantive drift; live GitHub HEAD/CI remains
authoritative and prevents self-referential monitor loops.

