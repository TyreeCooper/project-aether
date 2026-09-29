# AETHER Phase 17 Closeout — Full Swap-Out

**Status:** REPOSITORY CONTROL-PLANE PREP CLOSED / RUNTIME ACTIVATION BLOCKED  
**Branch:** `aether-vnext-swapout`  
**Safety:** PAPER ONLY / LIVE HARD BLOCKED  
**Canonical phase name:** Phase 17 — Full Swap-Out

## Repository-side scope completed

The repository now contains the fail-closed control-plane contracts required to
prepare a Full Swap-Out without prematurely switching runtime authority:

1. Full Swap readiness assessment with explicit blockers for:
   - Phase-16 internal closeout;
   - Phase-16 deployed runtime-shadow proof;
   - vNext CI;
   - repository CI;
   - canonical vNext-book reconciliation;
   - restart/recovery verification;
   - rollback-path verification;
   - legacy-runtime authority retirement readiness;
   - PAPER ONLY;
   - LIVE BLOCKED.
2. Immutable Full Swap activation plan:
   - canonical runtime = `aether_vnext`;
   - legacy runtime authority is retired only in the plan;
   - rollback code is retained;
   - recovery begins OFFLINE;
   - reconciliation is required before arm;
   - live authorization remains false;
   - building the plan performs no runtime side effect.
3. OFFLINE rollback/recovery contract:
   - restore previous paper runtime;
   - no automatic re-arm;
   - operator confirmation required;
   - reconciliation required before arm;
   - PAPER ONLY / LIVE BLOCKED remains mandatory.
4. Read-only Full Swap status projection that distinguishes:
   - readiness;
   - planned activation;
   - rollback preparedness;
   - actual runtime-authority change.
5. Deployed runtime-evidence contracts that require one reviewed revision for:
   - Phase-16 shadow coexistence against the dedicated burn-in book;
   - restart evidence for mid-ticket, mid-order, and open-trade scenarios;
   - exact identity, cash, margin, position-state, and idempotency preservation;
   - clean reconciliation;
   - OFFLINE rollback with no automatic re-arm;
   - source artifact lineage;
   - non-synthetic evidence.
6. Evidence-bound Full Swap readiness:
   - runtime-shadow, restart/recovery, rollback, and book-reconciliation checks are
     derived from evidence objects rather than manually asserted cutover booleans;
   - all runtime-sensitive evidence must share one deployed revision.
7. Read-only runtime-evidence validator:
   - accepts an external JSON evidence bundle;
   - applies the canonical Phase-17 contracts;
   - emits readiness and blockers;
   - cannot connect to a broker/database, switch, start, arm, or live-enable a runtime.

## What Phase 17 has NOT done

The branch has **not**:

- changed actual runtime authority;
- stopped the current legacy trading loop;
- started a canonical vNext trading loop;
- deployed a Full Swap to production;
- merged PR #12;
- altered production `main`;
- authorized live execution;
- treated a plan or readiness object as proof of activation.

The current legacy runtime remains the actual runtime authority until the external
activation gate is satisfied and an explicit cutover is performed.

## Full Swap activation blockers

Actual Phase-17 activation remains blocked until all of the following are proved
at one reviewed revision:

1. Phase-16 deployed runtime-shadow evidence is verified against the isolated vNext
   burn-in PostgreSQL target.
2. The canonical vNext book is reconciled with no unresolved desync.
3. Restart/recovery behavior is verified in the target runtime.
4. The rollback path is verified and begins OFFLINE.
5. The existing paper runtime can be retired without losing reconciliation or rollback
   safety.
6. vNext and repository CI are green.
7. PAPER ONLY / LIVE HARD BLOCKED remains true.

A source-code plan, unit test, synthetic fixture, or CI-only shadow route is not a
substitute for the deployed runtime evidence. The new evidence contracts and validator
make that proof machine-checkable, but they do not create the proof themselves.

## Repository-side closeout criteria

The repository-control-plane preparation is internally closed when one branch head
satisfies:

1. both CI lanes green;
2. no unresolved TODO/FIXME/NotImplemented marker in Phase-17 modules;
3. readiness fails closed on missing Phase-16 runtime-shadow proof;
4. activation planning cannot perform runtime side effects;
5. rollback is OFFLINE/reconciliation-first and cannot auto re-arm;
6. status projection remains read-only and reports actual authority unchanged;
7. LIVE execution remains unauthorized;
8. synthetic runtime, restart, rollback, or book-reconciliation evidence is rejected;
9. runtime-sensitive evidence is revision-consistent and artifact-traceable;
10. the evidence validator is read-only and cannot perform a cutover.

## Phase handoff

Phase 17 cannot be marked **fully complete** until runtime authority actually changes
under the verified Full Swap gate. Phase 18 — Forward Paper Evidence remains separately
paused under the existing operator instruction; this repository-side Phase-17 work does
not resume or fabricate Phase-18 evidence.

## Current external gate

A read-only `AETHER vNext Burn-in Control Plane` readiness report has been requested
for PR #12 through the protected `aether-vnext-burnin` GitHub Environment. The run
requires an authorized environment reviewer before it can access the protected burn-in
configuration. Until that approval and the later deployed runtime observations occur,
Phase-17 runtime activation remains blocked.
