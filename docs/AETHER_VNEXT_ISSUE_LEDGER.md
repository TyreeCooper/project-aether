# AETHER vNext — Issue Ledger

**AETHER TRACE:** 2026-09-25 23:49 EDT  
**Branch:** `aether-vnext-swapout`  
**Rule:** no hidden debt. Every discovered issue is fixed, explicitly deferred with a dependency, or proven irrelevant.

## AETH-VN-001 — Legacy baseline sleeve tests are red

**Class:** legacy baseline defect  
**Discovered:** PR #12 repository-wide CI  
**vNext isolation CI:** GREEN  
**Repository-wide CI:** GREEN as of run #515  
**Blocks vNext development:** NO  
**Blocks final merge/cutover:** NO — repaired and verified

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

### Resolution

A legacy-only repair restored the intended broker-sleeve contract without importing
legacy code into vNext or making legacy behavior design authority for vNext.

Repair details:
- `PaperPortfolio` now owns a `SleeveBook` and persists/restores it.
- direct legacy opens debit the target sleeve and closes credit the same sleeve.
- two-phase filled intents can be applied without double-debiting the sleeve.
- later frozen futures seed margins are used for legacy paper futures.
- focused synthetic legacy risk/cap tests use an explicit test-only sleeve-overflow
  fixture rather than weakening normal broker-local capacity.
- vNext remains fully isolated from `app.*`.

Verification:
- repository-wide CI run #515: **365 passed, 1 warning**.
- AETHER vNext CI run #98: **SUCCESS**.


## Status vocabulary

- **OPEN** — unresolved and relevant.
- **CONTAINED** — isolated; cannot contaminate current vNext phase.
- **BLOCKS_PHASE** — must be resolved before the current phase closes.
- **BLOCKS_MERGE** — development may continue, but merge/cutover is forbidden.
- **CLOSED** — resolved with evidence.

**AETH-VN-001 status:** CLOSED.


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


## AETH-VN-003 — Superseded GitHub Actions runs appeared frozen

**Class:** CI orchestration / operator visibility  
**Discovered:** 2026-09-26 during Phase 4 start  
**Status:** CLOSED

### Facts

- A prior repository-wide run (#509) remained stuck inside `python -m pytest -q`
  even though the isolated vNext workflow for the same head completed successfully.
- A fresh run after the legacy sleeve repair completed normally, proving the repository
  test suite itself was not permanently deadlocked.
- Rapid sequential commits were also creating multiple overlapping PR workflow runs,
  which made the Actions page show several pending/red rows at once.

### Resolution

Both PR workflows now use concurrency cancellation so a newer commit supersedes older
in-progress work for the same branch. Both jobs also have a 10-minute timeout so a
runner cannot remain pending indefinitely without terminating.

Verification:
- repository-wide CI run #515: SUCCESS, 365 passed.
- AETHER vNext CI run #98: SUCCESS.

Historical failed/cancelled/stale rows may remain visible in the GitHub Actions history;
they are not the status of the current PR head.


## AETH-VN-004 — Entry bad_fill_through_stop wording conflicts with protective-stop geometry

**Class:** binding-spec ambiguity / explicit implementation erratum  
**Discovered:** Phase 5 Execution Engine conversion  
**Status:** CLOSED  
**Blocks Phase 5:** NO

### Conflict

The binding v4.2.1 execution addendum literally states:

- `Computed entry is through the stop (long fill >= stop) REJECT bad_fill_through_stop`.

The executable Playbook Pack independently and repeatedly defines protective stops as:

- LONG: `entry - ATR multiple`;
- SHORT: `entry + ATR multiple`.

The same execution addendum also defines the conservative stop-through condition:
a long protective stop is already through when the long-side conservative market is
at/below the stop.

Taken literally, `long fill >= stop` would reject an ordinary valid long entry
because a valid long protective stop is below entry. The literal inequality is
therefore incompatible with the executable protective-stop geometry.

### Explicit erratum

For vNext implementation, `bad_fill_through_stop` means the **computed entry fill is
on or beyond the protective stop in the loss direction**:

- LONG: `computed_fill <= hard_stop_price`;
- SHORT: `computed_fill >= hard_stop_price`.

This correction is explicit and auditable. The source text is not overwritten.

### Precedence and effect

The fill-time conservative-side `stop already through` test remains first and rejects
`market_changed`. The corrected `bad_fill_through_stop` comparison is therefore a
defensive second check on the computed entry price. Under a healthy, non-crossed book
and the default adverse 5 bps paper slippage, it should normally be unreachable after
the conservative-side stop-through gate.

This erratum changes no playbook setup, trigger, stop placement, sizing, route state,
or evidence rule. No route evidence reset is required. vNext forward evidence has not
started, so no sample is being reclassified.


## AETH-VN-005 — PostgreSQL immutable-trigger function had malformed dollar quoting

**Class:** migration correctness defect  
**Discovered:** Phase 5 persistence audit of revision 0003  
**Status:** CLOSED

### Finding

The frozen revision-0003 migration had generated the PostgreSQL PL/pgSQL body as
`AS $ ... $;` instead of a valid dollar-quoted body. SQLite contract tests could not
exercise that PostgreSQL-only statement, so ordinary unit CI did not reveal it.

### Resolution

Revision 0003 now uses an explicit `$aether$ ... $aether$` function delimiter.
A regression test asserts both delimiters in the migration text.

This was corrected before vNext deployment/cutover. No production schema was changed.
