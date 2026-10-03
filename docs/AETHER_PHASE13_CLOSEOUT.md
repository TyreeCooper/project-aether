# AETHER Phase 13 Closeout — News-Market Intelligence

Status: INTERNAL BUILD CLOSEOUT CANDIDATE
Branch: `aether-vnext-swapout`
Safety boundary: PAPER ONLY / LIVE HARD BLOCKED

## Internal scope completed

Phase 13 now has implemented and tested internal contracts for:

- F-007 source, raw-news, normalized-event, event-to-asset, market-response,
  and historical-analog objects;
- durable F-007 storage with append-only immutable evidence rows;
- primary macro schedule verification across approved BLS / Federal Reserve /
  BEA authority IDs without aggregator/primary-state conflation;
- per-asset source trust with candidate/trusted/untrusted/disabled states and
  explicit operator approval before trust;
- secure source-candidate staging that can only enter the registry as candidate;
- intelligence source health with healthy/partial/stale/degraded/unavailable/
  unconfigured states and caller-owned freshness thresholds;
- cross-source insufficient/aligned/conflict assessment without collapsing
  conflict or missing data to neutral;
- research-only event-reaction rollups at 5m/15m/30m/1h/4h/24h with
  no-lookahead and immutable market-data lineage;
- temporal community research with rolling baselines, sentiment velocity,
  discussion-volume ratio, source diversity, and growing/stable/fading
  narrative state;
- append-only intelligence shadow audits for exact component ablation cohorts;
- explicit no-order/no-trade-influence boundaries throughout the intelligence
  research path.

## External/source-definition gates

The repository does not currently bind authoritative implementation details for:

1. Federal Reserve and BEA source-specific parser/family mappings.
   The primary-verification core is built; adapters must not guess mappings.
2. Official/developer/governance source-package contents for each initial
   desk asset.
3. The external provider(s), credentials, and discovery rules that feed secure
   source-candidate staging.
4. Provider-specific licensing/terms configuration where required.

These are configuration/content/integration gates, not missing core Phase-13
architecture.

## Policy gates

The source of truth does not currently bind:

- the evidence/authority transition policy for a full
  VERIFIED / LIKELY / CONTRADICTED claim-state machine;
- weights or thresholds for a composite intelligence score;
- criteria that would permit intelligence to become a hard gate or trading
  influence.

AETHER must not invent those policies. Existing intelligence therefore remains
context/research/shadow only.

## Empirical gates

The following require accumulated historical evidence rather than more plumbing:

- baseline vs +macro vs +news vs +community vs +cross-asset ablations;
- incremental-alpha estimates;
- out-of-sample validation;
- any proposal for limited Vector Engine influence.

Forward-paper evidence remains separately owned by paused Phase 18.

## Scope owned by later phases

Floor Catalyst/Risk Radar presentation expansion and richer in-app source
editing are operator-interface work and belong to Phase 15 rather than keeping
Phase 13 open.

## Closeout rule

Phase 13 may be treated as internally code-complete once:

1. both CI lanes are green at the final closeout commit;
2. the final vNext source/tree audit contains no Phase-13 TODO/NotImplemented
   implementation marker;
3. external/source-definition and policy gaps above remain explicit rather than
   guessed; and
4. intelligence remains unable to create orders or enable trade influence.

If an authoritative source-of-truth revision later binds one of the gated
policies or external mappings, Phase 13 should reopen only for that explicit
delta.
