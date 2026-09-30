# AETHER vNext Runtime Product Registry Bindings

Status: external burn-in prerequisite. This document does not authorize LIVE.

Frozen product economics live in the canonical Product Registry. Real forward-paper
burn-in additionally requires reviewed, time-varying runtime facts. AETHER must not
invent executable symbols, provider identities, stale thresholds, futures contracts,
contract IDs, expiry dates, exchange-calendar identities, or equity-borrow policy.

## Required manifest

GitHub Environment `aether-vnext-burnin` supplies:

`AETHER_VNEXT_RUNTIME_BINDINGS_JSON`

Top-level shape:

```json
{
  "registry_version": "<operator-version>",
  "configuration_hash": "<canonical CONFIGURATION_HASH>",
  "bindings": [
    {
      "asset_id": "btc",
      "broker_symbol": "XBTUSD",
      "primary_market_source_id": "kraken_public",
      "fallback_market_source_id": null,
      "stale_threshold_ms": "<REQUIRED_POSITIVE_INTEGER>",
      "calendar_provider_id": null,
      "calendar_market_id": null,
      "current_contract": null,
      "market_data_contract_id": null,
      "expiry_utc": null,
      "next_contract": null,
      "shortability_provider_id": null,
      "shortability_stale_threshold_ms": null,
      "source_ref": "<reviewed source/ticket/provider reference>"
    }
  ]
}
```

The stale threshold is intentionally not supplied by the frozen seed and must be a
reviewed external value.

## Strict seed-universe rule

Real burn-in initialization requires exactly these 12 assets:

`btc, eth, eurusd, usdjpy, mes, mnq, mgc, mcl, us10y, nvda, tsla, pltr`

A partial strict manifest is not "complete." Missing or unexpected assets make the
strict import fail before any runtime-registry database mutation.

## Binding requirements by product

Every Campaign #1 asset requires:

- nonblank executable broker symbol;
- primary market-data source identity;
- positive market-data stale threshold;
- canonical configuration hash.

Exchange-calendar products additionally require:

- implemented calendar-provider identity;
- reviewed provider market identity where that provider requires one.

FX OTC does not require an exchange-holiday provider. Its frozen calendar contract is
the explicit 24x5 weekend boundary plus the 16:59–17:05 ET rollover maintenance
window.

Futures additionally require:

- current executable contract;
- positive numeric provider contract ID when the provider identifies contracts that way;
- timezone-aware expiry;
- next contract;
- current broker symbol equal to current executable contract;
- current contract outside the frozen 48-hour roll cutoff.

IBKR equities additionally require a reviewed positive `market_data_contract_id`
(conid). Equity short routes require:

- implemented shortability-provider identity;
- positive shortability stale threshold;
- fresh provider-derived borrow evidence at Phase A.

Long equity routes do not depend on locate availability.

## Implemented market-source state

Current repository capability:

| Assets | Source | Repository state |
|---|---|---|
| BTC, ETH | Kraken public WebSocket v2 | Implemented |
| MES, MNQ, MGC, MCL, US10Y | NinjaTrader DEMO market-data transport | Implemented |
| NVDA, TSLA, PLTR | IBKR Web API SMD top-of-book | Implemented |
| EURUSD, USDJPY | tastyfx FIX 5.0 SP2 / FIXT 1.1 | Public FIX layer implemented; provider-private session/spec/conformance pending |

A named source is not enough. Canonical preflight requires the reviewed source to have
an implemented repository capability for the asset. tastyfx remains intentionally
fail-closed as `provider_spec_pending` until its private FIX specification/session
contract is supplied and reviewed.

## Calendar state

- BTC/ETH: crypto 24x7, no external exchange-holiday provider.
- EURUSD/USDJPY: frozen FX OTC weekly/rollover contract, no exchange-holiday provider.
- Futures/equities: TradingHours-backed authoritative date-specific snapshot provider
  is implemented; reviewed `calendar_market_id` values remain external binding facts.

## Equity shortability state

IBKR shortability support is implemented from documented market-data fields:

- 7636 — shortable shares;
- 7637 — fee-rate raw value;
- 7644 — shortability descriptor;
- 6509 — market-data availability state.

AETHER persists immutable shortability evidence and stamps the exact evidence ID onto
a short OrderIntent when Phase A admits it. Delayed/frozen/not-subscribed evidence,
stale evidence, contract/provider mismatch, or insufficient shares cannot authorize
the short.

## Commissioning helpers

Repository-side no-fabrication tooling is available before provider sign-in:

- `aether_vnext_tradinghours_discovery.py` enumerates only TradingHours markets
  available to the authenticated subscription and does not bind a FinID automatically;
- `ibkr_instrument_discovery.py` preserves all returned equity contract candidates
  and does not choose a conid automatically;
- `ninjatrader_contract_discovery.py` preserves provider contract IDs, maturities,
  expiries, and front-contract flags without making the AETHER roll decision;
- `aether_vnext_provider_commissioning_readiness.py` projects the exact remaining
  external facts by provider without recording credentials or claiming account state;
- `aether_vnext_provider_freshness.py` measures provider cadence/latency evidence
  but cannot choose or write `stale_threshold_ms`.

These helpers reduce the authenticated commissioning pass to reviewed provider facts.
They do not convert candidates into runtime authority, and they do not bypass strict
manifest validation.

## Persistence identity

Runtime bindings live in `product_registry_state` and are content-hashed. Campaign
preflight freezes the exact runtime binding hash into each forward-paper campaign
route, preventing silent drift between evidence inspection and campaign persistence.

Strict import validates the entire manifest before persistence. A failed strict import
does not partially rewrite `product_registry_state`.

## Non-negotiable boundary

A complete binding manifest proves reviewed identity/configuration only. It does not
prove provider connectivity, quote health, calendar health, broker availability,
held-out evidence sufficiency, strategy profitability, or P11 readiness.

PAPER ONLY and LIVE HARD BLOCKED remain unchanged.
