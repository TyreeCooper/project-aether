# Project Aether — Fault Response Runbook

## Automatic trigger

Current automatic trigger:
- Repeated market-data failures or missing fresh marks.

The engine transitions to `FAULT`, enables the flatten lock, and stops automated entry evaluation.

## Operator response

1. Do not immediately re-arm.
2. Confirm the public market feed is healthy and current.
3. Inspect `GET /api/v1/status`.
4. Inspect `GET /api/v1/audit`.
5. Confirm `last_tick_age_ms` is within the configured freshness window.
6. Confirm consecutive market-data failures returned to zero.
7. Use step-up authorization on `POST /api/v1/risk/reset-fault`.
8. Verify the bot returns to `OFFLINE`.
9. Re-arm separately only after the cause is understood.

## Emergency flatten

`POST /api/v1/orders/flatten` requires normal operator authentication but intentionally does not require step-up authorization. Emergency risk reduction must not be delayed by the second authorization factor.

The paper engine flattens current BTC inventory at the paper execution gateway, engages the flatten lock, and returns to `OFFLINE`.

## Future live fault sources

Before live execution is enabled, the same FAULT path should also be wired to:
- venue/account reconciliation mismatch,
- stale authenticated account state,
- repeated order rejection,
- authentication failure,
- database durability failure when persistence is mandatory,
- execution slippage above configured hard limits,
- daily-loss and drawdown breach,
- venue maintenance/degraded state where detectable.

FAULT reset must never automatically re-arm the strategy.
