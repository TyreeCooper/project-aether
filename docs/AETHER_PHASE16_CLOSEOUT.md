# AETHER Phase 16 Closeout — Shadow Cutover

**Status:** INTERNAL SHADOW BUILD CLOSEOUT CANDIDATE / RUNTIME SHADOW EVIDENCE PENDING  
**Branch:** `aether-vnext-swapout`  
**Safety:** PAPER ONLY / LIVE HARD BLOCKED  
**Canonical phase name:** Phase 16 — Shadow Cutover

## Internal scope completed

Phase 16 now implements and tests the repository-side shadow path:

1. a GET-only vNext Unified Firm Floor mount contract;
2. a canonical vNext-book -> Floor snapshot projection using the frozen seed universe,
   current point-in-time book state, Governor HALT state, canonical marks, queue state,
   and open-position identity;
3. a guarded legacy-side mount in the existing FastAPI application;
4. a dedicated vNext burn-in database reader that fails closed with HTTP 503 when
   isolated vNext database configuration is missing or unreadable;
5. no legacy desk/Floor fallback and no second trading runtime;
6. diagnostic shadow telemetry for
   Universe -> WATCH -> FIRE -> SIZE -> READY -> ORDER -> OPEN;
7. first-killer distribution and stage dwell time;
8. explicit prior-policy shadow observations for "would have passed" /
   "would have blocked" comparison without creating an order;
9. read-only authority boundaries that prohibit Firm-state mutation, route mutation,
   Risk mutation, Governor reset, live enablement, or trade influence.

## Safety / coexistence boundary

The Phase-16 shadow path:

- exposes `GET /api/v1/vnext/floor`;
- exposes no POST/PUT/PATCH/DELETE mutation transport on that route;
- reads only from the dedicated `AETHER_VNEXT_*` burn-in database path;
- does not fall back to `desk.floor_snapshot()` or other legacy trading state;
- does not call `engine.start_loop()` and does not start a second runtime;
- keeps the replacement Floor PAPER ONLY / LIVE BLOCKED;
- treats shadow comparison as diagnostic only;
- records prior-policy counterfactual outcome only when supplied by an explicit
  comparison source and cannot convert that counterfactual into an order.

## Internal closeout criteria

The repository-side Phase-16 implementation is internally closed when all of the
following are green at one branch head:

1. isolated vNext CI;
2. repository CI including the Unified Firm Floor production build;
3. source/tree audit finds no Phase-16 TODO/FIXME/NotImplemented marker;
4. the shadow route remains GET-only;
5. the configured reader uses only the dedicated vNext burn-in database path;
6. missing/unreadable vNext database configuration fails closed rather than falling
   back to legacy state;
7. no Phase-16 bridge starts a second trading runtime;
8. shadow telemetry remains diagnostic and cannot create orders or enable trading;
9. PAPER ONLY / LIVE HARD BLOCKED remains green under the vNext isolation contract.

## Runtime shadow evidence still pending

Repository CI proves the contract and production-shaped mount path. It does **not**
prove that a deployed non-production application instance has successfully read a
real canonical Floor snapshot from the isolated burn-in PostgreSQL target.

Full Phase-16 runtime evidence therefore remains open until a reviewed non-production
run proves, at the same deployed revision:

- the legacy application starts normally;
- the vNext shadow route is mounted;
- the route reads the dedicated vNext burn-in database successfully;
- a canonical vNext Floor snapshot is returned;
- the existing legacy surface remains available during coexistence;
- no mutation route or second trading runtime is introduced;
- PAPER ONLY / LIVE HARD BLOCKED remains true.

No unit test or synthetic fixture may be substituted for that runtime observation.

## Phase handoff

Once the internal closeout commit is dual-green, repository-side work may proceed to
**Phase 17 — Full Swap-Out** preparation. Phase 17 must not interpret internal
Phase-16 code completion as live authorization or as proof that the runtime-shadow
evidence gate has been satisfied.
