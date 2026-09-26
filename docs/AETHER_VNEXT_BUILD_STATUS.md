# AETHER vNext — Build Status

**AETHER TRACE:** 2026-09-26 01:18 EDT  
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

### Phase 5 — Execution Engine: IN PROGRESS

Scope:
- two-phase READY → RESERVED → SUBMITTED → FILLED/REJECTED/CANCELLED lifecycle;
- broker-local cash/margin reservation without holding SQL open during adapter wait;
- 250 ms paper acknowledgement/fill latency;
- 15 s paper stale-submit timeout;
- all-or-none seed-twelve paper fills by default; PARTIAL remains first-class but disabled
  unless Policy explicitly enables it;
- conservative bid/ask entry and exit fills with 5 bps adverse slippage;
- market-changed/stale rejection and spread-doubling guard at fill time;
- signal consumption only on successful OPEN;
- terminal-state idempotency and crash/restart reconciliation;
- flatten path with conservative through-price stop handling;
- no live orders.

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
- no vNext strategy implementation yet;
- no legacy evidence imported into vNext;
- PR #12 remains DRAFT.

## Next build target

Continue Phase 5 Execution Engine. Implement only the execution physics that are
unambiguous in the frozen sources; any conflicting execution rule is logged and held
out rather than guessed.

Strategy conversion remains later in the locked roadmap:
Phase 6 Risk + Governor → Phase 7 Playbook Runtime → Phase 8 Scout/Sniper/Clerk.
