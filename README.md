# Project Aether

Automated Bitcoin (BTC/USD) operator console and execution engine.

**Status:** Phase 0 skeleton (foundations). Paper / sandbox only. This repository does not authorize live capital.

Specification: see `docs/` and the v1.1 functional specification.

## Architecture (v1)

| Layer | Stack |
| --- | --- |
| Dashboard | Next.js + Tailwind CSS |
| API / engine | Python 3.12, FastAPI, asyncio |
| Exchange adapter | CCXT (Kraken first; Coinbase Advanced portable) |
| Hot cache | Redis 7 |
| System of record | PostgreSQL 16 + Alembic |

Design constraints from the specification:

- Secrets never leave the backend.
- Execution uses the venue tape only.
- Fail closed: process restart leaves the bot OFFLINE.
- Withdraw / transfer API permissions are forbidden.

## Quick start (local)

```bash
cp .env.example .env
# edit OPERATOR_PASSWORD and OPERATOR_AUTH_SECRET
docker compose up --build
```

- API health: http://localhost:8000/api/v1/health
- API docs: http://localhost:8000/docs
- Dashboard: http://localhost:3000

## Repository layout

```
backend/          FastAPI application
frontend/         Next.js dashboard shell
docs/             Phase notes
docker-compose.yml
.env.example      Required variables (no secrets)
```

## Roadmap

0. Foundations (this commit)
1. Market data dual feed
2. Account snapshots and audit log
3. Risk Guard and paper execution
4. SMA crossover strategy
5. Hardening and go-live checklist
6. Limited live (minimum size only, after written approval)

## Safety

Do not place live API keys in this repository. Do not enable withdraw on any key. Do not set `AETHER_ENV=live` until Phase 5 exit criteria are met.
