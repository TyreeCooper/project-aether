# AETHER Phase 14 — Document Change Ledger

Canonical C9.5 fields are preserved below. Timestamps are the verified Git commit
author timestamps in UTC. This ledger records specification/build deltas; it does
not award evidence credit or authorize execution.

| Version | Timestamp | Section changed | Reason | logic_changed | evidence n reset | Superseded version/reference | Commit / source ref |
|---|---|---|---|---|---|---|---|
| P14-01 | 2026-09-29T12:50:13Z | C5.2 / C4 | Add Institutional Memory and P&L attribution contracts | yes | no | Phase-14 partial foundation | `63d3226f` |
| P14-02 | 2026-09-29T12:52:31Z | C5.2 / C4 | Add contract tests for memory and attribution semantics | no | no | P14-01 | `2a0445d5` |
| P14-03 | 2026-09-29T12:56:11Z | C5.2 / C4 | Persist institutional-memory and attribution ledgers | yes | no | P14-02 | `b67a3615` |
| P14-04 | 2026-09-29T13:00:09Z | C5.2 / C4 | Wire durable memory store operations | yes | no | P14-03 | `67d5e652` |
| P14-05 | 2026-09-29T13:37:32Z | C5.2 / C5.3 | Add no-lookahead historical decision-context retrieval | yes | no | P14-04 | `e9a0e7c5` |
| P14-06 | 2026-09-29T13:41:17Z | C5.2 / C5.3 | Query durable memory at a point-in-time cutoff | yes | no | P14-05 | `dc0e8b0b` |
| P14-07 | 2026-09-29T13:44:57Z | C4 | Add descriptive hierarchical P&L attribution rollups | yes | no | P14-06 | `c2423109` |
| P14-08 | 2026-09-29T13:49:06Z | C5.4 | Add crisis/regime experience archive contracts | yes | no | P14-07 | `d8f2bb38` |
| P14-09 | 2026-09-29T13:53:32Z | C5.4 | Persist crisis/regime archive schema revision 0031 | yes | no | P14-08 | `cbd025d0` |
| P14-10 | 2026-09-29T15:21:52Z | C5.4 | Wire durable crisis archive store | yes | no | P14-09 | `4692ec10` |
| P14-11 | 2026-09-29T15:23:43Z | C5.4 | Normalize persisted archive timestamps after CI exposed SQLite timezone loss | yes | no | P14-10 | `1546a6f1` |
| P14-12 | 2026-09-29T15:26:27Z | C5.5 | Add point-in-time failure history | yes | no | P14-11 | `857cbf52` |
| P14-13 | 2026-09-29T15:29:15Z | C5.2 / C5.4 / C5.5 | Integrate stored decision, failure, and crisis experience under one cutoff | yes | no | P14-12 | `bc0beeff` |
| P14-14 | 2026-09-29T15:33:11Z | C4 / C5.3 | Add association-only mechanism-vs-event performance matrix | yes | no | P14-13 | `606900c4` |
| P14-15 | 2026-09-29T16:18:17Z | C9.2 / C9.3 | Add daily/weekly Firm Review projections | no | no | P14-14 | `63507a03` |
| P14-16 | 2026-09-29T16:21:47Z | C9.4 / C9.5 | Add UTC/operator-local traceability and change-ledger contract | no | no | P14-15 | `c83f4a53` |
| P14-17 | 2026-09-29T16:22:52Z | C9.4 | First import repair attempt after CI collection failure | no | no | P14-16 | `4e83e545` |
| P14-18 | 2026-09-29T16:23:45Z | C9.4 | Restore valid traceability imports; dual CI subsequently green | no | no | P14-17 | `85152a6d` |
| P14-19 | 2026-09-29T16:27:55Z | Phase 14 closeout | Add static source/tree safety audit and internal closeout record | no | no | P14-18 | `ae1a8a67` |

## Evidence reset note

No Phase-14 change above resets strategy evidence `n`. Phase 14 records,
retrieves, attributes, and reviews existing evidence/experience domains. It does
not silently reclassify historical or counterfactual records as independent
held-out or forward-paper evidence.

## CI incident trace

Two bounded defects were surfaced by CI during Phase 14 and were not bypassed:

- `4692ec10`: SQLite returned persisted timestamps without timezone metadata;
  `1546a6f1` normalized stored timestamps to UTC before reconstruction.
- `c83f4a53` / `4e83e545`: a malformed literal backslash-n in the traceability
  import caused collection failure; `85152a6d` restored the valid import and
  passed AETHER vNext CI #700 and repository CI #1009.

The closeout audit commit `ae1a8a67` then passed AETHER vNext CI #701 and
repository CI #1010 before this ledger correction.
