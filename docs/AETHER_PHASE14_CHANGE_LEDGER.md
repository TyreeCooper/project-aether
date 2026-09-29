# AETHER Phase 14 — Document Change Ledger

Canonical C9.5 fields are preserved below. Timestamps are canonical UTC.
This ledger records specification/build deltas; it does not award evidence credit.

| Version | Timestamp | Section changed | Reason | logic_changed | evidence n reset | Superseded version/reference |
|---|---|---|---|---|---|---|
| P14-1 | 2026-09-29T12:50:13Z | C5.2 / C4 | Add Institutional Memory and P&L attribution contracts | yes | no | Phase-14 partial foundation |
| P14-2 | 2026-09-29T12:56:11Z | C5.2 / C4 | Persist memory, attribution, failure, counterfactual, and coverage ledgers | yes | no | P14-1 |
| P14-3 | 2026-09-29T13:00:09Z | C5.2 / C4 | Wire durable memory store | yes | no | P14-2 |
| P14-4 | 2026-09-29T13:15:00Z | C5.2 / C5.3 | Add no-lookahead historical decision context | yes | no | P14-3 |
| P14-5 | 2026-09-29T13:25:00Z | C4 | Add descriptive P&L attribution rollups | yes | no | P14-4 |
| P14-6 | 2026-09-29T13:40:00Z | C5.4 | Add crisis/regime archive and durable schema 0031 | yes | no | P14-5 |
| P14-7 | 2026-09-29T15:20:00Z | C5.4 / C5.5 | Add durable crisis store, failure history, and integrated experience context | yes | no | P14-6 |
| P14-8 | 2026-09-29T15:33:11Z | C4 / C5.3 | Add association-only mechanism-vs-event performance matrix | yes | no | P14-7 |
| P14-9 | 2026-09-29T16:00:00Z | C9.2 / C9.3 | Add daily/weekly Firm Review projections | no | no | P14-8 |
| P14-10 | 2026-09-29T16:24:00Z | C9.4 / C9.5 | Enforce UTC/operator-local traceability and change-ledger contract | no | no | P14-9 |

## Evidence reset note

No Phase-14 change above resets strategy evidence `n`. Phase 14 records,
retrieves, attributes, and reviews existing evidence/experience domains. It does
not silently reclassify historical/counterfactual records as independent
held-out or forward-paper evidence.
