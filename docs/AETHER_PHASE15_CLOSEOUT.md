# AETHER Phase 15 Closeout — New Operator UI / Floor

**Status:** INTERNAL UI BUILD CLOSED / PHASE-16 SHADOW MOUNT PENDING  
**Surface name:** Unified Firm Floor  
**Branch:** `aether-vnext-swapout`  
**Safety:** PAPER ONLY / LIVE HARD BLOCKED

## Canonical completion gate

Phase 15's source-bound Floor composition is:

**Full universe + Top 12 + seat queues + open cockpits + drawer**

The replacement UI now implements all five surfaces.

### Full universe

The Floor projection accepts every supported canonical asset station and exposes
dominant state, owner seat, first blocker/reason, mark, open-position count, and
canonical route IDs. It does not restrict the Floor to a ten-asset or hand-picked
universe.

### Top 12 attention board

The Floor exposes at most 12 unique attention stations. Rank is caller-owned and
must carry an `attention_basis_ref`; Phase 15 does not invent a ranking formula.

### Canonical seat queues

The Floor exposes the source-bound queue ownership:

- Scout -> WATCH;
- Sniper -> FIRE;
- Risk -> SIZE / REJECT;
- Clerk -> READY / REJECT;
- Portfolio -> ORDER;
- Governor -> HALT.

The broader Firm seat vocabulary remains available for station ownership without
inventing queues for seats whose queue state is not source-bound.

### Open position cockpits

Each open cockpit carries durable position/trade identity, asset, horizon, side,
quantity, entry, mark, hard stop, open timestamp, and OPEN/SEEING state.

### Inspection drawer

The UI opens a read-only inspection drawer from an actual canonical station.
Detailed market-observation, decision-lineage, evidence, and blocker references
render only when the canonical Floor snapshot supplies them. Missing lineage is
shown as unavailable; it is not synthesized and does not fall back to legacy state.

## HTTP/UI boundary

Phase 15 defines a GET-only `/api/v1/vnext/floor` router contract and the
responsive Next.js Floor that consumes that path.

The router is intentionally **not mounted into the legacy application in Phase 15**.
Mounting the vNext read surface beside the current runtime is the next
**Phase 16 — Shadow Cutover** responsibility. This prevents Phase 15 from silently
creating a second runtime or performing an early cutover.

Repository CI includes a real Next.js production build for the replacement Floor
in addition to backend tests.

## Authority boundary

The Phase-15 Floor:

- exposes no POST/PUT/PATCH/DELETE transport;
- cannot create an order;
- cannot mutate Risk;
- cannot reset Governor;
- cannot promote/demote a route;
- is a read-only projection;
- explicitly reports PAPER ONLY / LIVE BLOCKED;
- creates no second runtime.

## Phase handoff

Phase 15 is internally code-complete at the UI/contract boundary. Phase 16 may
shadow-mount the GET-only Floor against canonical vNext state and compare it with
the existing surface. Phase 16 must preserve all Phase-15 read-only and
paper/live-block invariants.
