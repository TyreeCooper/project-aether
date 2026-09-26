# AETHER vNext — Issue Ledger

**AETHER TRACE:** 2026-09-26 17:54 EDT  
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


## AETH-VN-006 — Sleeve inventory cardinality is ambiguous on multi-asset broker rows

**Class:** schema normalization / anti-invention control  
**Discovered:** Phase 5 closeout audit  
**Status:** CLOSED  
**Evidence reset:** NONE

### Conflict

v4.2.1 names `inventory_qty / inventory_avg` on the broker sleeve while each
broker sleeve is explicitly allowed to hold multiple instruments:

- Kraken: BTC + ETH;
- IBKR: NVDA + TSLA + PLTR.

A single scalar quantity and average price on one broker row would mix incompatible
units and prices.

### Resolution

vNext preserves the exact inventory concepts but normalizes them into
`sleeve_inventory`, keyed by:

`(broker_account_id, asset_id)`

Each row owns `inventory_qty`, `inventory_avg`, `updated_at_utc`, and optimistic
`row_version`. The broker ledger retains broker-level cash, reserve, margin, P&L,
fees, carry, settlement, and reconciliation fields.

Revision 0009 refuses to infer an asset if a development database somehow contains
non-zero scalar inventory, rather than silently assigning it to the wrong instrument.

This is relational normalization only. It changes no setup, entry, exit, sizing,
risk fraction, playbook state, or evidence sample.


## AETH-VN-007 — Spot/equity sleeve-equity wording can double-count reserved purchase notional

**Class:** binding accounting ambiguity  
**Discovered:** Phase 5 closeout audit  
**Status:** CLOSED  
**Blocks Phase 5 two-phase execution:** NO  
**Blocks Phase 6 consolidated-equity/risk denominator:** NO — resolved and verified

### Conflict

v4.2.1 simultaneously states:

1. `cash_reserved_usd` includes OpenTrade reserved notional/margin;
2. spot `inventory_mtm = inventory_qty × bid`;
3. `sleeve_equity = cash_available + cash_reserved + inventory_mtm + unrealized - fees_accrued`;
4. counting reserved purchase notional as extra equity is forbidden.

For a filled spot/equity long, adding both the purchase notional still represented in
`cash_reserved` and the full marked inventory value would count the same capital twice.

### Controlled normalization

Until Phase 6 implements the consolidated-equity projection, vNext will not expose a
risk denominator from that literal double-counting formula.

The Phase 6 projection must exclude the portion of `cash_reserved_usd` that backs
spot/equity-long inventory before adding that inventory's conservative marked value.
Equivalently: reserved purchase cost is capital transformed into inventory, not extra
equity.

The existing Phase 5 OPEN/FLAT cash-reservation lifecycle remains unchanged and is
already tested for conservation. No profitability/evidence calculation may use a
double-counted equity figure.

### Resolution

Phase 6 implemented the controlled normalization in `aether_vnext/equity.py` and the
durable-book Firm projection in `VNextStore.project_firm_equity()`.

For cash-purchase inventory, the projection subtracts the portion of
`cash_reserved_usd` backing spot/equity-long inventory before adding conservative
inventory market value. Margin-style positions keep reserved cash as capital and add
conservative unrealized P&L instead.

Risk now consumes the resulting consolidated Firm-equity projection. The projection
fails closed when an OPEN asset lacks a healthy two-sided current observation.

Verification:
- AETHER vNext CI #345 first proved the repaired book-backed equity path:
  **173 passed**.
- Phase 6 final implementation evidence at CI #354:
  **212 isolated vNext tests passed**.
- repository-wide CI #663:
  **507 passed, 2 warnings**.

**AETH-VN-007 status:** CLOSED.


## AETH-VN-008 — Exact canonical seed-12 cluster assignment is not source-bound

**Class:** binding policy gap / anti-invention control  
**Discovered:** Phase 6 Risk integration  
**Status:** CLOSED  
**Blocks generic Risk engine:** NO  
**Blocks route admission without approved cluster identity:** NO — canonical map recovered

### Resolution

Phase 7 recovered the canonical mapping from the bound Playbook Pack plus the source
cluster-netting law rather than importing legacy runtime labels:

- BTC, ETH -> crypto
- EURUSD, USDJPY -> fx
- MES, MNQ, NVDA, TSLA, PLTR -> us_beta
- MGC -> metal
- MCL -> energy
- US10Y / ZN -> rates

The mapping is frozen in `aether_vnext.playbooks.SEED_ASSET_CLUSTERS`.
Every bound playbook is tested to remain inside exactly one canonical Risk cluster.
Unknown asset cluster lookup fails closed.

Verification:
- AETHER vNext CI #363: **330 passed**.
- repository-wide CI #672: **625 passed, 1 warning**.

**AETH-VN-008 status:** CLOSED.


## AETH-VN-009 — Daily-loss Governor threshold has no binding numeric value

**Class:** versioned policy dependency / anti-invention control  
**Discovered:** Phase 6 Governor integration  
**Status:** CONTAINED  
**Blocks durable Governor HALT enforcement:** NO  
**Blocks automatic daily-loss HALT trigger:** YES

### Facts

- The Master requires a versioned daily-loss threshold.
- At the threshold, new risk must HALT while existing exposure remains managed unless
  an explicit flatten policy says otherwise.
- An older v3.1 addendum contains a 2.00% SOD-equity policy default and 3.00% hard cap.
- The later v5 / Pre-Code Freeze authority expresses daily-loss HALT as a versioned
  policy but does not promote a numeric daily-loss constant into the frozen vNext
  configuration contract.
- vNext therefore does not silently revive the older number without an explicit
  current-authority binding.

### Control

vNext does not invent a percentage or dollar threshold. Durable route/venue/product/
desk HALT enforcement, restart persistence, authenticated reset contract, and audit
history are implemented independently.

Automatic daily-loss triggering remains disabled/unbound until an approved versioned
Policy Book supplies the numeric threshold.


## AETH-VN-010 — Three Playbook exit contracts are source-incomplete

**Class:** binding playbook ambiguity / anti-invention control  
**Discovered:** Phase 7 exit-geometry conversion  
**Status:** CONTAINED  
**Blocks Phase 7 deterministic WATCH evaluation:** NO  
**Blocks affected route Ticket / READY materialization:** YES

### Facts

The bound source provides enough information to evaluate WATCH structure for all
three definitions, but not enough to materialize a unique complete ExitPlan:

1. `pb_eth_rider_v1_2`
   - explicitly inherits the crypto-swing stop construction;
   - does not explicitly bind its own time-stop, first-target, or structure-invalidation
     fields.

2. `pb_fx_range_v1_3`
3. `pb_eq_range_v1_3`
   - both bind stop distance = 1.0 x ATR, target = 12-bar midpoint, time = 90m;
   - neither binds the stop anchor from which the 1.0 x ATR distance is measured.

### Control

vNext preserves the exact known geometry and marks these definitions
`source_complete=False`. It does not assume entry +/- ATR for Family C and does not
silently clone missing ETH-rider ExitPlan fields.

Phase 8 must refuse ticket materialization for any WATCH candidate whose exit contract
is incomplete.

**AETH-VN-010 status:** CONTAINED.


## AETH-VN-011 — ETH rider cross-asset Risk hitch is not yet durable through the trade pipeline

**Class:** cross-asset Risk attribution / persistence dependency  
**Discovered:** Phase 7 closeout audit  
**Status:** CLOSED  
**Blocks generic Phase 6 Risk engine:** NO  
**Blocks affected ETH playbook Ticket creation:** NO — hitch lifecycle is durable

### Resolution

Phase 8 carries the source-bound 50% BTC asset-cap hitch end to end:

- Scout Setup lineage persists the playbook hitch metadata.
- Risk sizing applies the hitch as an additional BTC asset-cap constraint.
- pending RESERVED/SUBMITTED occupancy persists the hitch in the durable risk reservation.
- OPEN trades reconstruct hitch occupancy from durable playbook lineage after restart.
- hitch occupancy affects the BTC asset bucket only; it is not counted again against
  the ETH cluster or Firm portfolio totals.
- reconciliation detects hitch drift and fails closed.
- zero-fill terminal release and FLAT lifecycle remove the pending/open occupancy with
  the surrounding Risk reservation/trade lifecycle.

Verification:
- `test_phase8_risk_cost_hitches.py` proves cross-asset capacity capping and no
  cluster/portfolio double count.
- `test_phase8_durable_risk_hitches.py` proves pending occupancy, drift detection,
  and restart reconstruction.
- AETHER vNext CI #373: **392 passed**.
- repository-wide CI #682 clean rerun: **687 passed, 1 warning**.

**AETH-VN-011 status:** CLOSED.


## AETH-VN-012 — F-005 percentile-rank tie convention is not source-bound

**Class:** deterministic implementation normalization  
**Discovered:** Phase 8 Allocator v1 conversion  
**Status:** CONTAINED  
**Blocks Allocator operation:** NO  
**Blocks reproducibility:** NO — convention is explicit and tested

### Facts

F-005 requires the conservative-expectancy component to be a percentile rank inside
the current eligible FIRE batch. The frozen source does not specify:

- tie handling;
- whether the endpoints are inclusive/exclusive;
- the singleton-batch value.

### Control

vNext uses one explicit deterministic normalization:

- comparable batch minimum = 0;
- comparable batch maximum = 100;
- equal values share their average rank;
- a single comparable candidate receives neutral 50;
- candidates with fewer than 15 closed trades or missing conservative expectancy
  also receive neutral 50 as required by F-005 evidence sufficiency.

This normalization affects sequencing only. It cannot change eligibility, quantity,
Risk limits, cash reservation, or Governor state. If current source authority later
binds a different percentile convention, this implementation must be versioned rather
than silently changed.

**AETH-VN-012 status:** CONTAINED / NON-BLOCKING.


## AETH-VN-013 — Universal benchmark “not worse” scalar comparator is not source-bound

**Class:** profitability-evidence comparison ambiguity / anti-invention control  
**Discovered:** Phase 9 benchmark engine conversion  
**Status:** CONTAINED / NON-BLOCKING FOR METRIC GENERATION  
**Blocks trusted KEEP unless separately resolved:** YES

### Facts

Current authority requires:
- every route to carry explicit benchmark identity;
- candidate and baseline to use the same data/fill/cost engine;
- benchmark evidence to remain queryable;
- trusted KEEP to be “not worse than baseline.”

The source does not bind one universal scalar formula that converts multi-metric
candidate/baseline evidence into that final boolean across crypto, FX, futures,
rates, and equities.

### Control

Phase 9 computes candidate and benchmark results on an identical EconomicPath and
stores base/+25%/+50% metrics side-by-side. It does not infer a universal winner.
baseline_not_worse remains an explicit evidence fact that must come from a
source-bound route/benchmark comparator before KEEP_TRUSTED may pass.

**AETH-VN-013 status:** CONTAINED.
