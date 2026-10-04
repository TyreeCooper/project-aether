# AETHER vNext — Phase 9 Profitability Implementation Closeout

**Trace date:** 2026-09-26  
**Branch:** `aether-vnext-swapout`  
**Implementation head entering closeout:** `b6d9b22bb369d96ec505baf43180ae8287022307`

## Status

**Phase 9 / Part IV implementation: COMPLETE.**

This statement is an implementation claim only. It is **not** a claim that Aether has
demonstrated real profitability, completed empirical burn-in, or become eligible for
live money execution.

P11 requires sustained forward operation with no unresolved accounting/model defects
and sufficient OOS/trusted-route evidence. The code now measures and persists that
readiness, but real evidence must accumulate before `profitability_ready=true` may
be asserted.

## Part-IV completion map

| Part | Implementation status | Operational status |
|---|---|---|
| P1 ProfitabilityEvidence + Review | Complete | Available |
| P2 Research integrity ledger | Complete | Available |
| P3 Benchmark engine | Complete | Available; AETH-VN-013 comparator dependency contained |
| P4 Regime tagging | Complete | Available |
| P5 Cost/capacity stress | Complete | Available; route/product thresholds explicit |
| P6 Portfolio contribution | Complete | Available |
| P7 Drawdown/path diagnostics | Complete | Direct diagnostics available; resampling policy unbound |
| P8 Decay monitor | Complete | Available; materiality policy explicit |
| P9 Traffic/config experiments | Complete | Available |
| P10 Profitability operator projection | Complete | Read-only contract available |
| P11 Burn-in readiness assessment | Complete | **Real burn-in evidence pending** |

## Verified CI

- Repository CI #695 — SUCCESS — P10 projection fix.
- AETHER vNext CI #386 — SUCCESS — P10 projection fix.
- Repository CI #696 — SUCCESS — P11 readiness gate.
- AETHER vNext CI #387 — SUCCESS — P11 readiness gate.

## Safety boundary

- PAPER ONLY.
- LIVE HARD BLOCKED.
- Forced strategy entries OFF outside isolated execution validation.
- Profitability readiness has no live-execution authority.
- Production `main` remains untouched by the vNext replacement branch.
- PR #12 remains DRAFT.

## Next evidence phase

The next work is forward-paper burn-in and cutover readiness: accumulate natural
paper-forward/OOS evidence, evaluate P11 from real Firm snapshots, resolve or continue
to contain declared source-policy gaps, integrate the operator UI with the read-only
P10 projection, and only then assess a separate live-readiness phase if explicitly
authorized.
