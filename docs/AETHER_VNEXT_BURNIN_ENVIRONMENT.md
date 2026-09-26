# AETHER vNext Burn-in Environment Boundary

The forward-paper burn-in book must not reuse the legacy production runtime's database
configuration.

## Required GitHub Environment

Create a GitHub Environment named:

`aether-vnext-burnin`

Configure **one** database connection path:

- `AETHER_VNEXT_BURNIN_DATABASE_URL` for a dedicated non-production PostgreSQL
  database; or
- `AETHER_VNEXT_BURNIN_POSTGRESQL_CONNECTIONSTRING` plus the dedicated OIDC secrets
  `AETHER_VNEXT_BURNIN_CLIENT_ID`, `AETHER_VNEXT_BURNIN_TENANT_ID`, and
  `AETHER_VNEXT_BURNIN_SUBSCRIPTION_ID`.

Do not copy the production `DATABASE_URL` or
`AZURE_POSTGRESQL_CONNECTIONSTRING` variables into the vNext namespace merely to
make the workflow pass. The vNext connector never reads those legacy variable names.

## Manual control plane

Workflow: `.github/workflows/aether-vnext-burnin.yml`

It is workflow-dispatch only and refuses execution from `main`.

- `preflight` performs no database writes.
- `initialize_and_preflight` applies the vNext Alembic chain, bootstraps only the
  canonical policy snapshot, then performs the same read-only preflight.

Initialization does **not** seed capital, trades, evidence, held-out windows, campaigns,
or profitability results.

The preflight must return `startable=true` before campaign creation is permitted.
A missing baseline is evidence work to complete, not a reason to synthesize data.

PAPER ONLY and LIVE HARD BLOCKED remain unchanged.
