# AETHER vNext — Build Status

**AETHER TRACE:** 2026-09-26 13:55 EDT  
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
- AETH-VN-007 remains CONTAINED and does not invalidate Phase 5 execution.
- It **must be resolved before Phase 6 uses consolidated/sleeve equity as a Risk denominator**,
  because literal spot/equity reserve + inventory marking can double-count purchase notional.
- Conservative mark-to-market, consolidated-equity projection, and the four-layer
  Risk/Governor envelope are therefore the first Phase 6 accounting gate.


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

Phase 6 — Risk + Governor.

First close AETH-VN-007 by implementing a non-double-counted conservative broker-sleeve
equity projection and consolidated Firm equity. Only after that projection is frozen
and tested may Risk consume equity for the trade / asset / cluster / portfolio envelope.

Strategy conversion remains later in the locked roadmap:
Phase 7 Playbook Runtime → Phase 8 Scout/Sniper/Clerk.
