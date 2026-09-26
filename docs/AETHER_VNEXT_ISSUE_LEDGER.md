# AETHER vNext — Issue Ledger

**AETHER TRACE:** 2026-09-25 23:49 EDT  
**Branch:** `aether-vnext-swapout`  
**Rule:** no hidden debt. Every discovered issue is fixed, explicitly deferred with a dependency, or proven irrelevant.

## AETH-VN-001 — Legacy baseline sleeve tests are red

**Class:** legacy baseline defect  
**Discovered:** PR #12 repository-wide CI  
**vNext isolation CI:** GREEN  
**Repository-wide legacy CI:** RED  
**Blocks vNext development:** NO  
**Blocks final merge/cutover:** YES until resolved or legacy path/tests are retired by the cutover plan

### Evidence

The failing tests are all in the unchanged legacy runtime:

- `tests/test_sleeve_portfolio.py::test_open_position_spends_only_target_sleeve`
- `tests/test_sleeve_portfolio.py::test_close_position_returns_cash_to_same_sleeve`
- `tests/test_sleeve_portfolio.py::test_two_phase_fill_then_portfolio_does_not_double_debit`
- `tests/test_sleeve_portfolio.py::test_reject_does_not_open_inventory`
- `tests/test_sleeve_portfolio.py::test_payload_round_trip_keeps_sleeve_split`

Observed result: **5 failed, 312 passed** in the repository-wide backend test job.

The branch did not modify either side of the failing contract:

- `backend/app/paper_portfolio.py` blob SHA is identical on `main` and vNext:
  `7c2f10ce27a102a521f351d952aaffadcb516032`
- `backend/tests/test_sleeve_portfolio.py` blob SHA is identical on `main` and vNext:
  `13a2608859eb0020644164159d9efd7437a16d6c`

Therefore this is not a regression introduced by the replacement runtime.

### Current decision

Do **not** bend vNext around this legacy mismatch.

Keep the defect visible while replacement work continues behind the isolated vNext CI gate. Before final merge/cutover, choose exactly one controlled resolution:

1. retire the legacy runtime and its obsolete tests as part of the cutover commit; or
2. make an isolated legacy-only repair if the old runtime must remain active longer.

No legacy test or implementation is allowed to become design authority for vNext merely to make this check green.

## Status vocabulary

- **OPEN** — unresolved and relevant.
- **CONTAINED** — isolated; cannot contaminate current vNext phase.
- **BLOCKS_PHASE** — must be resolved before the current phase closes.
- **BLOCKS_MERGE** — development may continue, but merge/cutover is forbidden.
- **CLOSED** — resolved with evidence.

**AETH-VN-001 status:** CONTAINED + BLOCKS_MERGE.


## AETH-VN-002 — External market-data/calendar bindings are intentionally unbound

**Class:** planned external dependency / anti-invention control  
**Discovered:** Phase 2 Product Registry closure  
**Status:** CONTAINED  
**Blocks Phase 2 contract closure:** NO  
**Blocks route FIRE without binding:** YES

### Facts

- The Master requires each product row to identify market-data sources and a stale threshold.
- The frozen specification does not provide a numeric stale threshold for the seed products.
- The repository currently has a concrete Kraken public-data implementation for BTC/ETH.
- No new vNext provider identity is being invented for tastyfx, NinjaTrader, or IBKR market data.
- Non-crypto calendar decisions require a date-specific holiday/early-close provider. If none is supplied, vNext returns ineligible rather than assuming NORMAL.
- Futures require an exact `current_contract` and expiry before lifecycle FIRE is eligible. Family symbols and continuous research symbols cannot substitute for executable contracts.

### Control

The Product Registry explicitly represents BOUND vs UNBOUND market data and exposes binding functions. Until a product has an approved source, stale threshold, calendar exception provider where applicable, and futures contract binding where applicable, it cannot become execution-eligible.

This dependency is expected to be resolved in the market-data/adapter phases. It is not permission to use legacy strategy/data behavior as a fallback.
