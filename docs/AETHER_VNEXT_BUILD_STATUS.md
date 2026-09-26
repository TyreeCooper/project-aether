# AETHER vNext — Build Status

**AETHER TRACE:** 2026-09-25 23:55 EDT  
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

### Phase 2 — registry + clocks / market truth: IN PROGRESS

Implemented so far:
- binding Part III seed product math for all 12 assets;
- fee-schedule identifiers and paper-model descriptions;
- session-calendar identifiers and binding display summaries;
- MarketObservation hard-validity helper with caller-supplied stale threshold;
- completed-bar law using exchange timestamp first, two-second receive grace only
  when exchange timestamp is unavailable, and session-close handling.

Still required before Phase 2 closes:
- full canonical Product Registry row contract;
- explicit registry lifecycle / current_contract / roll cutoff state;
- authoritative calendar scheduler interface;
- product data-source/adaptor mapping without inventing provider details;
- fee/cost registry executable calculations and FX conversions;
- Product Registry completeness tests.

## CI state

### vNext CI

GREEN on the current replacement code path.

### Repository-wide legacy CI

Known baseline defect AETH-VN-001 remains visible:
5 legacy sleeve/portfolio tests fail while 312 pass. The failing source and tests
are byte-identical between main and the replacement branch, proving the failure was
not introduced by vNext. This defect is CONTAINED and BLOCKS final merge, but does
not control vNext design.

## Current safety

- production `main` is untouched by vNext;
- no vNext production deployment;
- no live orders;
- no forced strategy entries;
- no vNext strategy implementation yet;
- no legacy evidence imported into vNext;
- PR #12 remains DRAFT.

## Next build target

Finish Phase 2 Product Registry and calendar contracts, then proceed to the vNext
Firm book/persistence projections. Strategy conversion remains intentionally later.
