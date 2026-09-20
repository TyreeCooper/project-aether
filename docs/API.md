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
| `GET /audit` | Structured audit events |

## Mutating routes

| Route | Purpose |
| --- | --- |
| `POST /bot/start` | Arm the paper strategy |
| `POST /bot/stop` | Stop new automated activity without flattening inventory |
| `POST /orders/market?side=buy|sell` | Manual paper market ticket |
| `POST /orders/flatten` | Paper emergency flatten and engage flatten lock |
| `POST /risk/unlock` | Clear flatten lock |

Authentication and step-up authorization are not yet implemented. Do not expose these mutating routes to an untrusted public network.
