# AETHER vNext Burn-in Environment Boundary

Status: protected external burn-in environment and dedicated database isolation are
verified. Runtime Product Registry bindings, provider-specific requirements, and
empirical evidence remain separate gates. This document does not authorize LIVE.

## Non-negotiable isolation

Forward-paper burn-in must use a dedicated non-production PostgreSQL target. vNext
accepts only the dedicated `AETHER_VNEXT_*` database namespace and does not fall
back to legacy `DATABASE_URL` or `AZURE_POSTGRESQL_CONNECTIONSTRING`.

GitHub Environment name:

`aether-vnext-burnin`

Configure exactly one database path:

- `AETHER_VNEXT_BURNIN_DATABASE_URL`; or
- `AETHER_VNEXT_BURNIN_POSTGRESQL_CONNECTIONSTRING` plus the dedicated OIDC
  values `AETHER_VNEXT_BURNIN_CLIENT_ID`,
  `AETHER_VNEXT_BURNIN_TENANT_ID`, and
  `AETHER_VNEXT_BURNIN_SUBSCRIPTION_ID`.

Before migrations or campaign work, the control plane scans the configured database
for known legacy Aether public tables and fails closed if any are present.

## Required external configuration

The protected environment also carries:

- `AETHER_VNEXT_RUNTIME_BINDINGS_JSON` — reviewed seed-12 runtime Product Registry
  bindings;
- `AETHER_VNEXT_TRADINGHOURS_API_TOKEN` — authoritative exchange-calendar access
  for supported non-OTC products.

Provider/session credentials used by operator-local probes, such as IBKR brokerage
sessions or NinjaTrader DEMO market-auth material, are not made implicit requirements
of the GitHub-hosted burn-in workflow.

## Control-plane workflow

Workflow:

`.github/workflows/aether-vnext-burnin.yml`

Supported actions:

- `readiness_report` — read-only environment/book readiness audit;
- `preflight` — read-only canonical Campaign #1 preflight;
- `initialize_and_preflight` — migrate, bootstrap canonical policy, atomically apply
  the reviewed seed-12 binding manifest, then run canonical preflight;
- `initialize_kraken_probe` — initialize and run the public BTC/ETH Kraken ingress
  probe;
- `initialize_calendar_probe` — initialize and run the authoritative TradingHours
  calendar probe;
- `start_campaign` — re-run canonical preflight and persist Campaign #1 only when
  the same book is startable.

Initialization never seeds fake trades, held-out evidence, campaign evidence,
profitability results, or synthetic capital.

## Pre-merge approval labels

Before merge, the supported secret-bearing path is the same-repository PR label flow
on PR head branch `aether-vnext-swapout`. The workflow verifies the exact PR-head SHA
before secret-bearing steps and remains protected by the
`aether-vnext-burnin` Environment.

Recognized labels:

- `aether-vnext-burnin-readiness-approved`
- `aether-vnext-burnin-preflight-approved`
- `aether-vnext-kraken-probe-approved`
- `aether-vnext-calendar-probe-approved`
- `aether-vnext-burnin-start-approved`

Fork heads and other branch names are refused.

## Atomic runtime-binding import

Strict burn-in initialization now requires the exact canonical seed-12 asset universe.

With `--require-complete --require-seed-universe`:

1. the entire manifest is parsed;
2. the seed universe is checked for missing or unexpected assets;
3. every binding is validated against source/calendar/shortability capability gates;
4. only if the strict validation is clean is `product_registry_state` mutated.

A partial or incomplete strict manifest returns non-zero and leaves the runtime
registry unchanged.

## Readiness audit

`scripts/aether_vnext_burnin_readiness.py` is read-only.

It reports:

- database isolation;
- whether schema `aether_vnext` exists;
- whether every expected current schema table is present;
- exact seed-12 runtime-binding coverage;
- canonical Campaign #1 preflight status;
- exact blocker counts;
- blocker classes including external provider-spec, external runtime configuration,
  empirical evidence, source authority, environment initialization, safety invariants,
  and internal/unclassified contract failures.

The readiness action does not migrate, bootstrap, bind providers, create evidence,
or start a campaign.

## Artifacts

The control plane uploads durable JSON artifacts for the relevant actions, including:

- runtime binding report;
- burn-in readiness report;
- canonical burn-in preflight;
- Kraken market probe;
- TradingHours calendar probe;
- campaign-start record.

A non-startable readiness/preflight run remains inspectable through its artifact.

## Verified external environment boundary

PR #12 burn-in control-plane evidence verifies:

- protected `aether-vnext-burnin` Environment approval is enforced;
- dedicated PostgreSQL target `aether_vnext_burnin` is reachable and isolated;
- no known legacy Aether public tables were present before initialization;
- current vNext migrations and canonical policy bootstrap complete successfully.

## Current external gates

Repository implementation does not prove the following external facts:

- reviewed runtime values for all seed-12 assets;
- tastyfx private FIX session/specification/conformance details for EURUSD/USDJPY;
- real held-out research provenance sufficient for every canonical executable route;
- actual provider connectivity/health during operation;
- sustained forward-paper evidence or P11 profitability readiness.

PAPER ONLY and LIVE HARD BLOCKED remain unchanged.
