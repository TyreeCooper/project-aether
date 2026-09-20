# Project Aether — Current Architecture

Aether is still paper-only. Live exchange execution is intentionally blocked.

## Trading flow

```text
MarketDataProvider
      |
      v
Reference Strategy
      |
      v
EntryDecisionService
   |             |
   v             v
Profitability   Risk Guard
Gate
   \             /
      v
ExecutionGateway
      |
      v
PaperPortfolio
      |
      +--> structured AuditEvent
      +--> recent order/fill ledger
```

The current reference strategy is a long-only SMA 8/21 crossover. It exists to exercise the platform, not as a claim of profitable alpha.

## Module boundaries

- `app/market_data/` — price-provider contracts and the current CoinGecko paper provider.
- `app/strategy.py` — pure SMA reference signal logic.
- `app/profitability/` — fee/spread/slippage estimates and the economic entry gate.
- `app/risk.py` — fail-closed safety predicates.
- `app/services/` — application-level composition of profitability and risk decisions.
- `app/execution/` — normalized order/fill contracts and paper execution.
- `app/portfolio/` — cash, BTC, cost basis, realized/open P&L, drawdown, and trade statistics.
- `app/audit/` — structured audit envelope and current in-memory sink.
- `app/db/` — SQLAlchemy durable-ledger models, async sessions, and the optional ledger repository.
- `app/main.py` — versioned FastAPI operator API.
- `frontend/` — mobile-first Next.js operator console.

## Safety boundary

No module currently has a live venue trading adapter. The engine sets `live_blocked=True`, and the repository must remain paper-only until the live promotion gates in the functional specification are satisfied.

## Profitability boundary

The current SMA strategy does not produce a statistically justified expected forward move. Aether therefore does not fabricate one. The Profitability Gate reports modeled one-way execution cost but remains advisory in paper mode until a strategy supplies `expected_move_bps`.

## Persistence status

The PostgreSQL schema defines orders, fills, positions, account snapshots, audit events, strategy/risk configs, and reconcile events. Paper runtime persistence is implemented behind `AETHER_PERSISTENCE_ENABLED=false` so the simple local quick-start remains independent of PostgreSQL.

To enable durable paper state:

```bash
cd backend
alembic upgrade head
```

Then set:

```text
AETHER_PERSISTENCE_ENABLED=true
```

When enabled, paper orders, fills, portfolio snapshots, and structured audit events are written to PostgreSQL. On process restart Aether restores the most recent paper ledger but deliberately remains `OFFLINE`; the operator must explicitly arm it again. Persistence failure is currently best-effort in PAPER mode and does not authorize LIVE operation.
