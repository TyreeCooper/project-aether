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
- Add a read-only Kraken Spot account adapter.
- Verify API-key metadata and permissions.
- Require withdrawals disabled.
- Reconcile balances/positions without order placement.
- Persist reconciliation events.

### Stage 2 — validate-only order adapter
- Implement Kraken Spot order construction using `validate=true`.
- Submit the exact intended order shape for validation only.
- Require successful validation before any live promotion.
- Store request fingerprint and validation result.
- Never treat validation success as a fill.

### Stage 3 — qualified Spot test environment
If Kraken grants Spot test-environment access:
- Use separate test credentials.
- Run order lifecycle tests: submit, acknowledge, cancel, partial fill, duplicate client ID, reconnect, recovery.
- Run reconciliation fault injection.
- Validate kill-switch and restart behavior.

### Stage 4 — shadow mode
- Consume live market data and live account state.
- Generate decisions but send no orders.
- Compare hypothetical fills/costs against observed market conditions.
- Require stable operation over a defined evaluation window.

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
