# Project Aether API — v1

Base path: `/api/v1`

## Read routes

| Route | Purpose |
| --- | --- |
| `GET /health` | Process/paper-feed health summary |
| `GET /status` | Bot state, safety flags, data age, profitability-gate state |
| `GET /bot` | Full current paper-engine snapshot |
| `GET /account` | Cash/BTC/equity and execution-cost attribution |
| `GET /positions` | Current BTC/USD position |
| `GET /orders` | Recent in-memory paper orders |
| `GET /trades` | Recent in-memory paper fills |
| `GET /performance` | Net/gross P&L, costs, drawdown, and trade statistics |
| `GET /audit` | Structured audit events |\n| `GET /venue/kraken/readiness` | Read-only Kraken key and balance-read readiness |\n
## Mutating routes

| Route | Purpose |
| --- | --- |
| `POST /bot/start` | Arm the paper strategy |
| `POST /bot/stop` | Stop new automated activity without flattening inventory |
| `POST /orders/market?side=buy|sell` | Manual paper market ticket |
| `POST /orders/flatten` | Paper emergency flatten and engage flatten lock |
| `POST /risk/unlock` | Clear flatten lock |\n| `POST /risk/reset-fault` | Reset FAULT after freshness checks; remains OFFLINE |\n
Authentication and step-up authorization are not yet implemented. Do not expose these mutating routes to an untrusted public network.


## Authentication

All routes except `GET /health` require operator authentication.

Send:

```text
Authorization: Bearer <OPERATOR_AUTH_SECRET>
```

High-risk mutations additionally require:

```text
X-Aether-Step-Up: <OPERATOR_STEP_UP_SECRET>
```

Step-up is required for:
- `POST /bot/start`
- `POST /orders/market`
- `POST /risk/unlock`\n- `POST /risk/reset-fault`

Emergency stop/flatten remain available with normal operator authentication so the extra authorization step cannot delay a safety action.

The browser console does not contain either secret at build time. They are entered into in-memory UI state for the current tab.


## Arming gates

`POST /bot/start` fails closed when any enabled prerequisite is unhealthy.

Current optional gates:
- PostgreSQL persistence: when `AETHER_PERSISTENCE_ENABLED=true`, the database must pass a round-trip health probe.
- Venue reconciliation: when `VENUE_RECONCILIATION_REQUIRED=true`, the most recent successful reconciliation must be newer than `VENUE_RECONCILIATION_MAX_AGE_SECONDS`.

A successful reconciliation does not arm the bot. It only satisfies the reconciliation prerequisite.


## Shadow mode

Set `SHADOW_MODE_ENABLED=true` to record strategy decisions without sending them to the paper execution gateway.

- `GET /api/v1/shadow/decisions` returns the in-memory decision window.\n- `GET /api/v1/shadow/performance` returns the isolated hypothetical portfolio and after-cost performance metrics.\n- Buy, sell, and stop decisions are recorded with mark, quantity, position context, whether the decision would have executed, and the hypothetical execution result.\n- When PostgreSQL persistence is enabled, decisions are also written to `shadow_decisions`.
- Shadow mode never promotes itself to paper or live execution.

## Kraken validate-only order checks

`POST /api/v1/venue/kraken/validate-order` requires operator + step-up authorization and dedicated `KRAKEN_VALIDATE_API_KEY` / `KRAKEN_VALIDATE_API_SECRET` credentials.

The venue adapter hard-codes `validate=true`; it exposes no live-order method. A successful response means the order shape passed Kraken validation. It is not a fill and does not alter Aether's portfolio.

When persistence is enabled, the request fingerprint and sanitized validation result are stored in `venue_validation_events`.


Shadow execution uses an isolated portfolio and the configured paper fee/spread/slippage model. It does not mutate the normal paper portfolio, order ledger, or fill ledger.
