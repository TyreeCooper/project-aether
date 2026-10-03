# AETHER Volatility Percentile Convention v1

**Status:** operator-approved specification decision  
**Scope:** PAPER ONLY / LIVE BLOCKED

The frozen Playbook Pack requires:

- `realized_vol(trigger_interval, 14)`;
- comparison against the percentile distribution from the prior 90 calendar days
  of that same interval;
- Family A/B eligibility at percentile `[40,85]`, inclusive;
- Family C range eligibility below 40.

The frozen source does not define percentile ranking, tie handling, interpolation,
or whether the trigger observation participates in its own reference distribution.
On 2026-09-27 the operator delegated that missing implementation convention.

## Binding

For a completed trigger bar with close time `T`:

1. Calculate current RV14 using AETHER Indicator Convention v1.
2. Build the reference distribution from PIT RV14 observations whose same-asset,
   same-interval completed-bar evaluation timestamps fall in
   `[T - 90 calendar days, T)`.
3. Exclude the trigger RV14 from its own reference distribution.
4. Each historical RV14 may use only bars available at its own historical
   evaluation timestamp.
5. Require enough pre-window completed bars to warm RV14 from the beginning of the
   90-day reference window. This is data-integrity coverage, not an invented
   statistical minimum sample count.
6. If the resulting reference count `N == 0`, fail closed.
7. Rank with deterministic empirical midrank:

   `percentile = 100 * (L + 0.5 * E) / N`

   where `L` is the number of reference RV14 values strictly below current RV14
   and `E` is the number exactly equal to current RV14.
8. Use no interpolation and no rounding before volatility-band classification.

An all-tied distribution therefore maps to percentile 50 rather than 0 or 100.

## Classification

The existing source-bound runtime thresholds remain unchanged:

- `percentile < 40` -> below-40 regime;
- `40 <= percentile <= 85` -> eligible mid-volatility regime;
- `percentile > 85` -> above-85 regime.

This convention resolves calculation mechanics only. It does not promote playbook
evidence state or fabricate historical results.
