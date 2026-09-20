# Project Aether — Live Promotion Plan

Aether remains PAPER ONLY.

## Venue testing constraint

Kraken's public demo environment is for Futures. Spot REST/WebSocket/FIX test environments are available to qualified clients through onboarding. For normal Spot accounts, Kraken documents a `validate` parameter for order submission that validates an order without placing it.

Because Aether is a BTC/USD spot system, this repository must not quietly substitute the public Futures demo as a Spot sandbox. That would test a materially different product and risk model.

## Promotion stages

### Stage 0 — current
- Paper execution only.
- Public Kraken Spot WebSocket v2 market data.
- CoinGecko warm-up history.
- Operator bearer authentication.
- Step-up authorization for arm/trade/unlock/fault reset.
- Market-data watchdog and fail-closed FAULT state.
- Optional PostgreSQL paper ledger.

### Stage 1 — credential validation
Implemented foundation:
- Read-only Kraken Spot account adapter.
- API-key metadata/permission readiness checks.
- Withdrawal-capable permissions are rejected by readiness assessment.
- Position reconciliation policy and persisted reconciliation events.

Still required before Stage 1 is complete:
- Wire authenticated venue balance reads into an operator-triggered reconciliation endpoint.
- Require a successful reconciliation immediately before arming whenever venue-account reconciliation is enabled.

### Stage 2 — validate-only order adapter
Implemented foundation:
- Kraken Spot order construction with `validate=true` hard-coded in a dedicated adapter.
- Dedicated validation credentials separate from read-only reconciliation credentials.
- Step-up protected validation endpoint.
- Request fingerprint and validation-result persistence when PostgreSQL is enabled.
- Validation success is explicitly reported as non-fill/non-live execution.

Still required before Stage 2 is complete:
- Exercise the adapter against an operator-owned Kraken Spot account.
- Capture successful and rejected validation fixtures.
- Add restart/idempotency regression coverage using persisted fingerprints.

### Stage 3 — qualified Spot test environment
If Kraken grants Spot test-environment access:
- Use separate test credentials.
- Run order lifecycle tests: submit, acknowledge, cancel, partial fill, duplicate client ID, reconnect, recovery.
- Run reconciliation fault injection.
- Validate kill-switch and restart behavior.

### Stage 4 — shadow mode
Implemented foundation:
- Execution-suppressed strategy decision recording.
- In-memory operator view and optional PostgreSQL persistence.
- Buy/sell/stop decisions carry mark, quantity, position context, and would-execute state.

Still required before Stage 4 is complete:
- Couple shadow decisions to authenticated live account state.
- Calculate hypothetical fill/cost outcomes against observed market conditions.
- Define and pass the stable-operation evaluation window.

### Stage 5 — micro-live
Only after explicit operator approval:
- Tiny notional.
- No leverage.
- No derivatives.
- Hard daily-loss and max-position caps.
- Reconciliation before arm and after every fill.
- Kill switch on stale data, auth failure, reconciliation mismatch, or repeated venue errors.

## Promotion blockers

Live execution must remain blocked if any of the following are true:
- CI is red.
- Operator or step-up auth is not configured.
- Market data is stale.
- Reconciliation is mismatched or unavailable.
- Database persistence is required but unhealthy.
- API permissions are broader than required.
- Withdrawal permission is enabled.
- Expected trading edge does not clear modeled costs when profitability enforcement is enabled.
- Restart/recovery behavior has not been tested.
