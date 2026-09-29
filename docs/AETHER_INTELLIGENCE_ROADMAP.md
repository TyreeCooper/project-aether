# Aether Intelligence Expansion — Canonical Roadmap

Updated: 2026-09-21
Repository: TyreeCooper/project-aether

This file is the durable implementation ledger for the Aether Intelligence Expansion.
Chat threads are reference material; repository behavior, tests, and this ledger are the
source of truth for implementation status.

## Non-negotiable invariants

1. MARKET OPPORTUNITY, MARKET EXPLANATION, and TRADING DECISION remain separate systems.
2. Community, news, macro, and crypto-event intelligence cannot directly create orders.
3. Missing/degraded intelligence is never silently converted to neutral.
4. Live execution remains blocked until the separate live-readiness gate is explicitly cleared.
5. No-lookahead: research may use only information Aether could have known at that timestamp.
6. External intelligence is promoted only through observe -> record -> research -> shadow score ->
   out-of-sample validation -> limited influence.
7. Primary-source verification and aggregator discovery are distinct states.

## Current implementation status

| Backlog | Capability | Status | Current implementation |
|---|---|---|---|
| 1 | 24h Opportunity Envelope | IMPLEMENTED | Kraken current/open/high/low/net/range/range position/volume/spread + ATR(14) 1m, 60m realized vol, relative volume, liquidity state |
| 2 | Multi-window opportunity | IMPLEMENTED | 1h, 4h, 12h, 3d, 7d, 30d |
| 3 | Opportunity Capture Analytics | IMPLEMENTED | MFE, MAE, available move, entry/exit efficiency, gross/net capture, missed favorable move, fees, slippage, and cost drag are recorded per closed paper trade |
| 4 | Asset Intelligence State | PARTIAL | Canonical per-asset context exists; support/resistance and complete catalyst/source profile remain |
| 5 | Cross-asset relationships | PARTIAL | BTC corr, ETH corr, BTC beta, relative strength vs BTC and desk; desk-index correlation remains |
| 6 | Market regime classification | IMPLEMENTED-SHADOW | Transparent heuristic regime; no trade influence |
| 7-8 | Move attribution + confidence | PARTIAL | BTC-aligned, macro, corroborated-news and technical candidate drivers with confidence; residual decomposition remains |
| 9 | Lead/lag analysis | IMPLEMENTED-RESEARCH | Uses persisted first-seen timestamps and forward price snapshots; no causality claim |
| 10-12 | Macro intelligence / risk calendar | GATED-INTEGRATION | Forex Factory discovery + BLS verification remain; vNext primary-verification core supports BLS/Federal Reserve/BEA authority IDs, while source-specific Fed/BEA parser-family mappings remain externally unbound |
| 13-14 | Risk windows / recovery | OBSERVE-ONLY | Macro risk windows visible; enforcement and dynamic market-normalization recovery remain disabled pending validation |
| 15 | Holiday/thin liquidity | PARTIAL | Spread-based liquidity state exists; holiday/session participation model remains |
| 16 | Crypto-native events | IMPLEMENTED-SHADOW | Optional CoinMarketCal adapter; exact vs estimated dates preserved; no enforcement |
| 17 | Asset news | IMPLEMENTED-SHADOW | GDELT asset-specific discovery; primary/official asset channels remain |
| 18-20 | Community intelligence | IMPLEMENTED-RESEARCH/GATED-SOURCES | Reddit shadow feed plus vNext rolling baselines, sentiment velocity, discussion-volume ratio, source diversity, narrative trends, manipulation/rumor indicators; broader verified source bundles remain externally configured |
| 21 | Narrative detection | IMPLEMENTED-RESEARCH | Keyword narratives plus vNext no-lookahead temporal growing/stable/fading state from current-vs-baseline mention arithmetic |
| 22 | Rumor vs verified fact | GATED-POLICY | Unconfirmed/corroborated metadata + rumor intensity exist; VERIFIED/LIKELY/CONTRADICTED transition criteria are not source-bound and are intentionally not invented |
| 23 | Community manipulation | PARTIAL | Duplicate messaging, pump language, author concentration, heuristic risk score; platform-level bot evidence remains |
| 24 | Community lead/lag | IMPLEMENTED-RESEARCH | Generic observation timing study covers community observations |
| 25 | Automatic source discovery | IMPLEMENTED-FOUNDATION/GATED-PROVIDER | vNext secure candidate staging requires explicit operator acceptance and can only enter as candidate; external discovery provider/adapter remains unbound |
| 26-29 | Floor intelligence boards | SUBSTANTIAL | Opportunity ranking, dedicated catalyst board, event/liquidity risk radar, and source health are mounted in live markup |
| 30-35 | Asset intelligence panels | SUBSTANTIAL | Opportunity, windows, quality/regime, cross-asset, attribution/news, community, risk, capture are visible |
| 36 | Intelligence history | IMPLEMENTED | 5-minute asset snapshots + deduplicated observation ledger |
| 37 | Intelligence score | NOT STARTED | Subscores must remain visible if added |
| 38 | Three-system separation | ENFORCED | Intelligence remains context, not an order generator |
| 39 | Intelligence-to-strategy interface | PARTIAL | Standardized asset_context exists; Vector Engine consumption intentionally disabled |
| 40 | Hard gates vs soft signals | PARTIAL | Existing market/execution gates remain; intelligence hard-gate promotion not enabled |
| 41 | Source confidence engine | PARTIAL | Source tiers/status + corroboration/official verification metadata |
| 42 | Duplicate-news suppression | IMPLEMENTED | Near-duplicate story clustering; cross-domain corroboration is not primary verification |
| 43 | Time-aware event storage | IMPLEMENTED-FOUNDATION | first_seen, published/source times, scheduled event times retained where available |
| 44 | Historical event reaction DB | IMPLEMENTED-RESEARCH | Durable research-only 5m/15m/30m/1h/4h/24h event-reaction measurements and materialized rollups with immutable lineage |
| 45 | Historical community evaluation | IMPLEMENTED-FOUNDATION | Lead/lag research can score community observations as history accumulates |
| 46 | Asset-specific source profiles | GATED-SOURCES | vNext persisted operator-controlled trust registry + secure candidate staging exist; official/developer/governance package contents remain externally/source-definition gated |
| 47 | Data-quality controls | IMPLEMENTED-FOUNDATION | healthy/partial/stale/degraded/unavailable/unconfigured freshness state plus deterministic insufficient/aligned/conflict cross-source assessment; no missing/conflict-to-neutral coercion |
| 48 | API layer | PARTIAL | floor/assets/sources/risk/crypto-events/history/research endpoints exist |
| 49 | Storage model | IMPLEMENTED-FOUNDATION | Generic history plus durable vNext source/trust/health/conflict, F-007 news/event, event-reaction, historical-analog, and shadow-audit tables through schema revision 0029 |
| 50-51 | Settings/source registry | SUBSTANTIAL | Intelligence/feed health visible; per-asset source trust is persisted and operator-controlled by protected API; richer in-app editing remains |
| 52 | Asset onboarding expansion | PARTIAL | Kraken add + history seed exists; source/community discovery and event sensitivity remain |
| 53 | Notifications | NOT STARTED | In-app intelligence alerts remain |
| 54 | Intelligence audit trail | IMPLEMENTED-SHADOW | Append-only vNext shadow audit records baseline vs exact intelligence-component cohorts without order/trade authority |
| 55 | Validation ladder | ENFORCED-BY-DESIGN | New external intelligence remains shadow/observe only |
| 56 | No-lookahead safeguards | IMPLEMENTED-FOUNDATION | Aether first_seen is persisted independently of published/event time |
| 57 | Incremental alpha measurement | EVIDENCE-GATED | Shadow audit infrastructure exists; estimates require sufficient accumulated history and out-of-sample evidence |
| 58 | Future Floor objective | PARTIAL | Portfolio, movers, opportunity and risk visible; causal explanation board still maturing |
| 59 | Future asset-page objective | SUBSTANTIAL | Most requested context is visible; support/resistance/source depth/validated decision influence remain |
| 60 | Final architecture | INTERNAL-BUILD-CLOSEOUT | Core vNext intelligence contracts, persistence, health/conflict, event reactions, temporal community research, and shadow audit are built; external mappings, policy binding, empirical validation, and influence promotion remain intentionally gated |

## Remaining gated sequence after internal Phase-13 closeout

1. Bind authoritative Federal Reserve/BEA parser and event-family mappings, then wire their source-specific adapters.
2. Supply official/developer/governance source-package definitions for the initial desk assets.
3. Connect approved external discovery providers to the secure candidate-staging boundary.
4. Bind claim-state and intelligence-score policy only through an authoritative source-of-truth revision.
5. Complete Floor Catalyst/Risk Radar and richer source editing in Phase 15.
6. Accumulate sufficient history, then run baseline vs +macro vs +news vs +community vs +cross-asset ablations.
7. Run out-of-sample validation.
8. Only proven features may be proposed for limited Vector Engine influence.

## Strategy/live status

The Intelligence Expansion does not change the separate strategy-readiness result.
The current strategy has not demonstrated a profitability basis sufficient for live promotion.
Live trading remains blocked. No intelligence feature added in this expansion overrides that.
