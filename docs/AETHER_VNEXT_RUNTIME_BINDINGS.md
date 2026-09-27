# AETHER vNext Runtime Product Registry Bindings

Status: external burn-in prerequisite. This document does not authorize LIVE.

The frozen Product Registry contains product economics and broker families. Real
forward-paper burn-in additionally needs time-varying external facts that the source
specification requires but does not numerically bind. Those values must be reviewed
and supplied; the code must not invent them.

## Required secret

GitHub Environment `aether-vnext-burnin` must contain:

`AETHER_VNEXT_RUNTIME_BINDINGS_JSON`

The value is a JSON object:

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
      "current_contract": null,
      "expiry_utc": null,
      "next_contract": null,
      "shortability_provider_id": null,
      "source_ref": "<reviewed source / ticket / provider reference>"
    }
  ]
}
```

The example intentionally leaves the stale threshold unresolved. The Master requires
a stale threshold, but the frozen seed does not bind a numeric value.

## Completeness rules

Every asset entering Campaign #1 requires:

- a nonblank executable broker symbol;
- a named primary market-data source;
- a positive stale-threshold value;
- a calendar-provider identity for every non-24x7 product;
- for futures: current executable contract, expiry timestamp, and next contract;
- for borrow-required equities: a shortability/locate provider identity;
- a configuration hash equal to the canonical vNext freeze.

For futures, `broker_symbol` must equal `current_contract`. A current contract
inside the frozen 48-hour roll cutoff is not burn-in-ready.

The runtime binding record is stored in `product_registry_state`. Campaign
preflight freezes the binding content hash into every campaign route so a binding
cannot silently change between evidence inspection and campaign persistence.

## Seed-twelve unresolved external fields

| Asset | Source-bound facts already present | External facts still required |
|---|---|---|
| BTC | Kraken family; XBTUSD; crypto 24x7; long-only | approved stale threshold; optional fallback; source reference |
| ETH | Kraken family; ETHUSD; crypto 24x7; long-only | approved stale threshold; optional fallback; source reference |
| EURUSD | tastyfx family; FX economics/calendar class | executable broker symbol; market-data source; stale threshold; calendar provider |
| USDJPY | tastyfx family; FX economics/calendar class | executable broker symbol; market-data source; stale threshold; calendar provider |
| MES | NinjaTrader family; MES economics | current contract; expiry; next contract; market-data source; stale threshold; calendar provider |
| MNQ | NinjaTrader family; MNQ economics | current contract; expiry; next contract; market-data source; stale threshold; calendar provider |
| MGC | NinjaTrader family; MGC economics | current contract; expiry; next contract; market-data source; stale threshold; calendar provider |
| MCL | NinjaTrader family; MCL economics | current contract; expiry; next contract; market-data source; stale threshold; calendar provider |
| US10Y | NinjaTrader family; executable family ZN; 1/64 tick = $15.625 | current ZN contract; expiry; next contract; market-data source; stale threshold; calendar provider |
| NVDA | IBKR family; equity economics; short requires locate | executable broker symbol; market-data source; stale threshold; calendar provider; shortability provider |
| TSLA | IBKR family; equity economics; short requires locate | executable broker symbol; market-data source; stale threshold; calendar provider; shortability provider |
| PLTR | IBKR family; equity economics; short requires locate | executable broker symbol; market-data source; stale threshold; calendar provider; shortability provider |

## Workflow behavior

The approved preflight label resolves to `initialize_and_preflight`:

1. validate the dedicated burn-in database;
2. refuse a legacy database target;
3. migrate the vNext schema;
4. bootstrap the canonical policy snapshot;
5. apply `AETHER_VNEXT_RUNTIME_BINDINGS_JSON`;
6. fail if any supplied binding is incomplete;
7. run the canonical 74-route campaign preflight;
8. upload both the binding report and preflight report.

The campaign-start approval path does not rewrite runtime bindings. It reads the
persisted binding state, re-runs canonical preflight, freezes each binding hash, and
only then persists Campaign #1.

## Non-negotiable boundary

A successful binding manifest proves that required external identities and lifecycle
facts were supplied. It does not by itself prove provider connectivity, quote health,
holiday-feed health, broker availability, or profitability. Those remain runtime and
empirical gates. PAPER ONLY and LIVE HARD BLOCKED remain unchanged.
