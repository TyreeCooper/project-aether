# AETHER vNext — Phase 0 Legacy Isolation Control

**AETHER TRACE:** 2026-09-25 23:34 EDT  
**Replacement branch:** `aether-vnext-swapout`  
**Legacy baseline SHA:** `879736630edf5f41ede90258a4596bf3fff8c053`  
**Specification authority:** Firm Master Blueprint v5.0 + Playbook Pack v1.4 FULL + Pre-Code Freeze v1.0  
**Operating mode:** PAPER ONLY  
**Live execution:** HARD BLOCKED

## Phase 0 law

AETHER vNext is a specification-driven replacement build.

Legacy code is preserved in Git for rollback and historical reference only. It has no
design authority over vNext. Compatibility with legacy strategy behavior is not a
requirement.

Code under `backend/aether_vnext/` MUST NOT import `app` or any `app.*` module.
If infrastructure is worth reusing, it must be deliberately reimplemented or migrated
behind a vNext-owned contract and validated against the frozen specification.

## Current active legacy runtime map

The repository scan at the Phase 0 baseline found these active legacy dependencies:

- `backend/app/main.py` imports both `app.desk.desk` and `app.engine.engine` during
  the current application lifecycle.
- `backend/app/desk.py` imports the existing playbook, routing, PairBook, paper
  portfolio, persistence, intelligence, news, and runtime-mode stack.
- `backend/app/routing.py` hard-codes all horizons to `trend_breakout` version `v3`.
- `backend/app/playbooks.py` is the current 12-book implementation and imports
  strategy primitives from `app.strategy`.
- `backend/app/strategy.py` still identifies itself as trend-aware SMA strategy
  primitives and explicitly preserves legacy 5-minute behavior for existing callers.
- `backend/app/db.py` still contains a persisted default strategy value of
  `sma_crossover`.
- `backend/app/pair_book.py` remains coupled to legacy playbooks, strategy exits,
  sessions, execution matrix, fill model, instruments, and paper execution.
- `.github/workflows/main_aether-prod-api.yml` currently verifies the
  `AETHER-LOAD-003-B9` / `strategy_test` legacy runtime after production deploy.

These are migration inputs, not vNext contracts.

## Isolation gate

Phase 0 is not complete until all of the following are true:

1. vNext imports without importing `app` or `app.*`.
2. vNext remains PAPER ONLY and LIVE BLOCKED.
3. No legacy strategy, playbook, routing, PairBook, engine, or persistence module is
   imported into the vNext runtime.
4. Legacy production continues to exist unchanged until vNext cutover is validated.
5. vNext receives its own persistence namespace before strategy evidence is written.
6. No legacy fills, route statistics, strategy state, or evidence are counted as vNext
   evidence.
7. Any reused infrastructure is migrated explicitly and tested against the frozen vNext
   contract; reuse is never implicit.
8. Cutover occurs only after the replacement runtime passes its phase gates.

## Cutover order

`preserve -> isolate -> rebuild -> validate -> shadow -> cut over -> observe -> retire legacy runtime paths`

Deletion of old runtime code is intentionally later than disconnection. Git remains the
rollback record even after legacy runtime paths are retired.

## Current Phase 0 commits

- `07be1b9c3adf3aff767fba2c8130343ac214aac7` — establish isolated vNext package.
- `f78e2e09e4297b40c23ae888dcb93907e493c9af` — enforce no-legacy-import and live-block tests.

## Next Phase 0 task

Create the vNext canonical domain core boundary and dedicated persistence namespace
without importing legacy runtime objects. Do not implement trading strategy logic yet.
