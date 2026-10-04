# AETHER Market Truth & Execution — Canonical Standalone Specification

**Status:** canonical private-use design  
**Runtime scope:** PAPER only; LIVE orders are out of scope  
**Authority rule:** later layers may not skip, replace, infer, or average around earlier layers.

This document is standalone. Earlier AETHER documents are not required to interpret the market-truth and execution contract.

## 1. Asset Universe

The Asset Universe is a registry of instruments that may exist. Each row contains only instrument identity and market-structure facts required to identify the instrument: canonical instrument ID, asset class, tick size, lot size, and session calendar.

**No prices, providers, fees, routes, adapters, quotes, or fills live in the Asset Universe.**

The Asset Universe does not publish market truth and does not communicate directly with the executable tape.

## 2. Provider Card

A Provider Card defines a provider's contractual capabilities. Observation and execution are separate capabilities even when the same firm supplies both.

Every Provider Card contains:
- provider ID;
- role: `observe`, `execute`, or `both`;
- venue;
- fee schedule;
- entitlement.

**Fees live only on the Provider Card.** Instrument identity does not grant observation or execution authority.

## 3. Route

For each routed instrument, exactly one Provider Card is the executable provider. Witness providers are named separately.

A human establishes or changes the execution route. Automatic execution-venue switching is forbidden.

Transport failover is allowed only when it preserves the same economic venue/provider route. A second socket or transport path to the same venue is not a route change.

The Route tells Market Fabric which executable and witness transports are authorized to open.

## 4. Market Fabric

Market Fabric consumes the Route. It does not select the execution venue.

There is one adapter contract per venue. The adapter parses provider packets into canonical fields; it does not average, synthesize, interpolate, carry forward, or calculate an executable price.

### Executable tape

The executable tape represents the fresh coherent book of the human-selected route venue exactly as printed:
- bid;
- ask;
- last only if the venue printed a last;
- bid size and ask size when printed;
- venue timestamp when printed;
- local receive timestamp.

A missing provider field is `null`, never zero.

Execution state has exactly three values:
- `EXECUTABLE`
- `STALE`
- `NOT_OBSERVED`

Execution state comes only from the executable route book.

If the executable transport dies, becomes incoherent, or exceeds its stale policy, executable bid/ask are blanked even when every witness is healthy.

### Witness evidence

Witnesses sit beside executable truth. They may corroborate, challenge, or be absent, but they cannot overwrite the executable bid or ask.

Evidence state has exactly six values:
- `NO_WITNESS`
- `CONTESTED`
- `DIVERGED`
- `SINGLE_SOURCE`
- `DEGRADED`
- `FULL`

`NOT_OBSERVED` is not an evidence state.

A visual `CORROBORATED` badge is presentation only. Consumers read execution state and evidence state as separate axes.

Any midpoint, composite, fair value, residual, spread statistic, or other calculated figure is explicitly **NON-EXECUTABLE**.

## 5. Execution

Execution reads only:
- the executable Route;
- executable bid/ask and book depth published by Market Fabric;
- the fee schedule from the executable provider's Provider Card.

Execution sends only to the provider that owns the human-selected Route.

A PAPER fill walks the executable book or rejects. It cannot use a witness price, midpoint, composite, fair value, or carried-forward last. The recorded fill is checked against the exact book snapshot that was live for the decision.

The tape does not invent a fill. A completed PAPER fill is written back only as an execution fact.

## Communication Direction

Authority moves in one direction:

`Asset Universe → Provider Card → Route → Market Fabric → Execution`

The only write-back is an immutable execution fact after a PAPER fill.

The Asset Universe does not talk to the tape. The Route opens authorized sockets. Market Fabric publishes executable book state and independent evidence state. Execution subscribes to the executable book and provider fee card.

## First Proof Gate

Before a second executable instrument or any paid feed is admitted, AETHER must prove one instrument end to end using one public executable socket. Witnesses are permitted only if they are also public transports.

The proof must demonstrate:

1. **Executable cable pull:** terminate the executable transport; executable price blanks rather than falling back to a witness.
2. **Witness divergence:** move a witness 1% away; evidence state may change, but executable bid/ask remain byte-for-byte unchanged.
3. **Deterministic replay:** replay the captured provider packets and timing events; execution/evidence states reproduce deterministically.

No second executable route is allowed until all three assertions pass.

## Explicitly Out of Force Until First Proof Passes

- microstructure signals;
- cross-asset watermarks;
- automatic execution-venue changes;
- options scale;
- shares in the executable column without their own authorized executable socket;
- futures in the executable column without their own authorized executable socket;
- spot FX in the executable column without its own authorized executable socket.

This restriction does not prevent those instruments from existing in the Asset Universe. It prevents AETHER from claiming executable market truth without an authorized route and socket.

## Safety Boundary

This architecture is private-use only. PAPER execution is permitted only inside existing AETHER PAPER-only controls. LIVE remains hard blocked. No component in this contract may enable LIVE execution.
