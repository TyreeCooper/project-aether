# Project Aether — Kraken Spot UAT Acceptance Suite

Status: specification only. Live execution remains blocked.

This suite defines the minimum acceptance evidence required before Aether may
advance from validate-only/shadow operation toward a separate micro-live
implementation.

## Gate A — credentials and account boundary

Pass only if all are true:

- UAT/test credentials are separate from production credentials.
- Withdrawal capability is absent.
- Required query/order permissions are documented.
- Credentials are injected through the deployment secret store, never source.
- Revocation procedure is tested.
- Clock/nonce behavior survives process restart.

## Gate B — market-data lifecycle

Test:

1. Subscribe to BTC/USD Spot market data.
2. Verify initial snapshot/first usable mark.
3. Verify normal incremental updates.
4. Force disconnect.
5. Verify reconnect without duplicate strategy execution.
6. Simulate stale data.
7. Confirm watchdog enters FAULT after threshold.
8. Confirm FAULT reset requires fresh data and returns to OFFLINE.

Evidence:
- timestamps,
- correlation IDs,
- reconnect count,
- stale-mark age,
- audit events.

## Gate C — order lifecycle

For each supported order shape:

- construct,
- validate,
- submit in UAT only,
- acknowledge,
- query,
- partial fill where supported,
- full fill,
- cancel,
- cancel already-complete order,
- unknown order lookup,
- duplicate client-order ID.

Acceptance:
- local order state matches venue state,
- duplicate client IDs never create duplicate economic exposure,
- every transition is auditable,
- restart does not lose the venue/local relationship.

## Gate D — reconciliation

Scenarios:

- exact match,
- dust within tolerance,
- mismatch above tolerance,
- local position missing,
- venue position missing,
- stale venue snapshot,
- venue API unavailable.

Acceptance:
- above-tolerance mismatch enters FAULT,
- flatten lock engages,
- mismatch is persisted,
- operator acknowledgement/reset is required,
- successful reconciliation never auto-arms the strategy.

## Gate E — persistence and restart

1. Start with healthy PostgreSQL.
2. Persist order/fill/account/reconciliation state.
3. Stop process during an open position.
4. Restart.
5. Restore durable state.
6. Confirm bot starts OFFLINE.
7. Reconcile venue state.
8. Require explicit re-arm.

Failure injection:
- DB unavailable before arm,
- DB unavailable after order acknowledgement,
- duplicate persistence attempt,
- corrupted/incomplete local record.

Acceptance:
- persistence failure cannot silently promote the bot to an armed state.

## Gate F — shadow-mode quality

Run shadow mode against live Spot market/account observations without order
submission.

Capture:
- strategy signal,
- mark,
- modeled costs,
- would-execute decision,
- hypothetical fill price,
- observed post-signal path,
- hypothetical gross/net P&L.

Promotion evidence must include enough observations to evaluate:
- net expectancy after modeled costs,
- cost-model error,
- drawdown,
- win/loss distribution,
- regime dependence,
- decision frequency.

No profitability conclusion is permitted from a single trade, single day, or
unrepresentative market regime.

## Gate G — emergency controls

Verify:

- operator stop,
- emergency flatten path,
- market-data FAULT,
- reconciliation FAULT,
- credential revocation,
- restart after FAULT,
- out-of-band kill procedure from the functional specification.

Emergency risk reduction must not depend on the strategy loop being healthy.

## Gate H — promotion decision

UAT passes only when:

- CI is green on the exact candidate commit,
- all UAT cases have timestamped evidence,
- no unresolved severity-1 safety defect exists,
- reconciliation is deterministic,
- restart is fail-closed,
- shadow-mode evidence is complete,
- the operator signs the promotion record.

Passing UAT does not itself enable live trading. Live execution must be
implemented in a separate reviewed change with explicit capital/risk limits.
