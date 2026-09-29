# AETHER Phase 12 Closeout — Alpha Factory / Research Warehouse

Status: INTERNAL BUILD CLOSEOUT CANDIDATE
Branch: `aether-vnext-swapout`
Safety boundary: PAPER ONLY / LIVE HARD BLOCKED

## Scope closed internally

Phase 12 now has implemented and tested internal contracts for:

- canonical research hypothesis, experiment, dataset, run, fold, evidence, review, and promotion lineage;
- frozen evidence-bearing experiment/run identity and append-only promotion lineage;
- point-in-time research warehouse manifests, canonical bar identity, immutable content hashing, and PIT selection;
- replay feature construction with canonical asset/interval identity, completed-bar semantics, numeric integrity, and source lineage;
- frozen 90-day volatility-percentile convention, including window geometry, count arithmetic, percentile reconstruction, convention version, and boolean/numeric fidelity;
- held-out route/work-item planning, fold assembly, replay-result coverage, evidence-window provenance, and durable fold/dataset containment;
- held-out provenance revalidation before forward-paper preflight use;
- research-integrity diagnostics for parameter mining, sample starvation, outlier dependence, and regime concentration;
- deterministic review/promotion boundaries with no execution, Risk, Governor, or automatic-promotion authority.

## Intentionally unbound policy

The source does not bind universal numeric thresholds for the following Alpha Factory diagnostics:

- `parameter_mining_threshold_unbound`
- `sample_starvation_threshold_unbound`
- `outlier_dependence_threshold_unbound`
- `regime_concentration_threshold_unbound`

`ResearchIntegrityPolicy` therefore accepts optional bound thresholds and reports
`UNBOUND_POLICY` when source authority has not supplied them. Phase 12 must not invent
those numbers to manufacture a CLEAR result.

## Empirical evidence deferred outside internal build closeout

The repository explicitly states that current runtime/Kraken history is not sufficient to
establish profitability. Promotion evidence ultimately requires longer clean historical
data, multiple non-overlapping out-of-sample windows, realistic execution assumptions,
and forward-paper evidence.

Those are empirical/evidence requirements, not missing Alpha Factory architecture.
Forward-paper evidence remains a separate paused Phase 18 workstream.

## Authority boundary

Phase 12 remains research-only:

- no live trading;
- no automatic promotion;
- no order authority;
- no Risk or Governor override;
- no fabricated profitability;
- no weakening of held-out or PIT requirements.

## Closeout rule

Phase 12 may be treated as internally code-complete once:

1. both repository CI lanes are green at this closeout commit;
2. no remaining source-bound internal implementation gap is identified by the final audit;
3. unbound policy thresholds remain explicitly unresolved rather than guessed; and
4. empirical profitability/forward-paper evidence remains deferred to its owning evidence phase.

If a later source-of-truth revision binds the unresolved thresholds or adds a new Phase-12
requirement, Phase 12 should reopen only for that explicit delta.
