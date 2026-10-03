# AETHER vNext — Indicator Convention v1

**AETHER TRACE:** 2026-09-27 21:38 EDT  
**Status:** OPERATOR-APPROVED SPECIFICATION DECISION  
**Scope:** deterministic indicator calculation only  
**Mode:** PAPER ONLY  
**Live execution:** HARD BLOCKED

## Why this decision exists

The frozen Firm Master Blueprint v5.0 and Playbook Pack v1.4 require EMA20/EMA50,
ATR14, and `realized_vol(trigger_interval, 14)`, but do not fully bind the numerical
calculation conventions needed for deterministic replay. Pre-Code Freeze v1.0
requires the implementation to stop rather than invent those missing rules.

On 2026-09-27 the operator explicitly approved the following calculation contract as
**AETHER Indicator Convention v1**. This is a new specification decision. It must not
be represented as wording that already existed in Master v5, Playbook v1.4, or
Pre-Code Freeze v1.0.

## Binding formulas

### EMA20 / EMA50

Inputs are completed-bar closes only.

For period `N`:

1. require at least `N` completed closes;
2. initialize with the arithmetic mean of the first `N` closes;
3. set `alpha = 2 / (N + 1)`;
4. for every later completed close, update:

`EMA_t = alpha * close_t + (1 - alpha) * EMA_(t-1)`

No library-default seed or alternate smoothing convention is permitted.

### ATR14

True range for a completed bar is:

`TR_t = max(high_t - low_t, abs(high_t - close_(t-1)), abs(low_t - close_(t-1)))`

ATR14 requires 14 true-range observations:

1. initial ATR14 = arithmetic mean of the first 14 TR observations;
2. each later completed bar uses Wilder smoothing:

`ATR_t = (13 * ATR_(t-1) + TR_t) / 14`

### Realized volatility 14

Use the trailing 14 completed-bar log returns:

`r_t = ln(close_t / close_(t-1))`

Then:

`RV14 = sqrt(sum(r_t^2))`

There is **no annualization**. The Playbook requirement to compare RV14 with the
prior 90 calendar days of the same trigger interval remains unchanged.

## Replay and data invariants

- forming or future bars are prohibited;
- input bars must be timezone-aware, completed, strictly ordered, and from one
  asset/interval;
- prices must be finite and positive;
- the implementation may not substitute pandas/TA-library defaults for these formulas;
- this decision does not alter playbook periods, regime bands, side eligibility,
  execution physics, risk ceilings, evidence rules, or campaign requirements.

## Safety boundary

This convention only resolves deterministic indicator math. It does not establish
strategy profitability, held-out evidence sufficiency, burn-in readiness, or live
authorization. PAPER ONLY / LIVE HARD BLOCKED remains unchanged.
