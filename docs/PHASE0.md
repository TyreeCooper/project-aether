# Phase 0 — Foundations

Exit criteria from the specification:

- Health endpoint green locally.
- No secrets in git.
- Compose brings up API, web, Redis, and PostgreSQL.
- Schema migrations tool present (Alembic), even if tables are minimal.

## Included

- FastAPI `/api/v1/health` and `/api/v1/bot` stub (state OFFLINE).
- Next.js dashboard shell matching the five-widget information architecture.
- `.env.example` with required names and empty exchange keys.
- GitHub Actions lint workflow (syntax-level).

## Not included (later phases)

- Venue WebSocket
- CCXT live calls
- Risk Guard
- Strategy evaluation
- Real flatten
