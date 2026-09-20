# Azure — single-site paper deployment

Aether can run as one Azure Web App. FastAPI serves the API and a same-origin fallback operator console at `/`.

## Web App

1. Azure Portal → Create → **Web App**
2. Resource group: `aether-rg`
3. App name: choose a globally unique name
4. Publish: **Code**
5. Runtime: **Python 3.12**
6. Deployment Center → GitHub → repository `TyreeCooper/project-aether`
7. Deploy the reviewed branch/commit; do not point production at an unreviewed feature branch.

Startup command:

```text
cd backend && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Required application settings

```text
AETHER_ENV=paper
MARKET_DATA_PROVIDER=kraken_ws
OPERATOR_AUTH_SECRET=<long-random-secret>
OPERATOR_STEP_UP_SECRET=<different-long-random-secret>
AETHER_PERSISTENCE_ENABLED=false
VENUE_RECONCILIATION_REQUIRED=false
```

Do not place secrets in source control or frontend environment variables.

For read-only Kraken readiness/reconciliation, optionally add:

```text
KRAKEN_READ_API_KEY=<read-only-key>
KRAKEN_READ_API_SECRET=<read-only-secret>
```

The key should be limited to the minimum account-query permissions required by Aether. Withdrawal-capable permissions are rejected by the readiness assessment.

## Persistence

Before setting `AETHER_PERSISTENCE_ENABLED=true`, provision PostgreSQL, set `DATABASE_URL`, and run:

```text
cd backend
alembic upgrade head
```

When persistence is enabled, an unhealthy database blocks bot arming.

## Safety

Aether remains paper-only. Do not configure trading credentials or expose live execution until the repository's live-promotion gates are explicitly completed.
