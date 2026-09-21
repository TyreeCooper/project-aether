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
| 10-12 | Macro intelligence / risk calendar | PARTIAL | Forex Factory aggregator + BLS primary schedule verification; Fed/BEA primary verification remains |
| 13-14 | Risk windows / recovery | OBSERVE-ONLY | Macro risk windows visible; enforcement and dynamic market-normalization recovery remain disabled pending validation |
| 15 | Holiday/thin liquidity | PARTIAL | Spread-based liquidity state exists; holiday/session participation model remains |
| 16 | Crypto-native events | IMPLEMENTED-SHADOW | Optional CoinMarketCal adapter; exact vs estimated dates preserved; no enforcement |
| 17 | Asset news | IMPLEMENTED-SHADOW | GDELT asset-specific discovery; primary/official asset channels remain |
| 18-20 | Community intelligence | PARTIAL | Asset-specific Reddit shadow feed, sentiment, narratives, manipulation/rumor indicators; broader source bundle/velocity/baselines remain |
| 21 | Narrative detection | PARTIAL | Keyword narratives exist; temporal growing/stable/fading clustering remains |
| 22 | Rumor vs verified fact | PARTIAL | Unconfirmed/corroborated-unverified news + rumor intensity; full VERIFIED/LIKELY/CONTRADICTED state machine remains |
| 23 | Community manipulation | PARTIAL | Duplicate messaging, pump language, author concentration, heuristic risk score; platform-level bot evidence remains |
| 24 | Community lead/lag | IMPLEMENTED-RESEARCH | Generic observation timing study covers community observations |
| 25 | Automatic source discovery | NOT STARTED | Must require operator approval before trust |
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
| 44 | Historical event reaction DB | PARTIAL | Snapshots + observations support reaction research; dedicated materialized event-reaction rollups remain |
| 45 | Historical community evaluation | IMPLEMENTED-FOUNDATION | Lead/lag research can score community observations as history accumulates |
| 46 | Asset-specific source profiles | PARTIAL | Persisted per-asset source trust registry exists; current seeded coverage is Reddit only; official/developer/governance bundles remain |
| 47 | Data-quality controls | SUBSTANTIAL | healthy/partial/stale/degraded/unavailable/unconfigured states and rotating-feed coverage now exist; cross-source conflict scoring remains |
| 48 | API layer | PARTIAL | floor/assets/sources/risk/crypto-events/history/research endpoints exist |
| 49 | Storage model | PARTIAL | Generic research-grade snapshot + observation tables; specialized normalized tables can be added when queries justify them |
| 50-51 | Settings/source registry | SUBSTANTIAL | Intelligence/feed health visible; per-asset source trust is persisted and operator-controlled by protected API; richer in-app editing remains |
| 52 | Asset onboarding expansion | PARTIAL | Kraken add + history seed exists; source/community discovery and event sensitivity remain |
| 53 | Notifications | NOT STARTED | In-app intelligence alerts remain |
| 54 | Intelligence audit trail | FOUNDATION | Observations are recorded; decision-change audit becomes relevant only after intelligence is allowed influence |
| 55 | Validation ladder | ENFORCED-BY-DESIGN | New external intelligence remains shadow/observe only |
| 56 | No-lookahead safeguards | IMPLEMENTED-FOUNDATION | Aether first_seen is persisted independently of published/event time |
| 57 | Incremental alpha measurement | NOT STARTED | Requires sufficient accumulated intelligence history |
| 58 | Future Floor objective | PARTIAL | Portfolio, movers, opportunity and risk visible; causal explanation board still maturing |
| 59 | Future asset-page objective | SUBSTANTIAL | Most requested context is visible; support/resistance/source depth/validated decision influence remain |
| 60 | Final architecture | IN PROGRESS | Core intelligence -> validation -> asset state path exists; learning/promotion path remains intentionally closed |

## Recommended next build sequence from current state

1. Complete primary-source macro verification for Federal Reserve and BEA.
2. Build per-asset source registry with trust states and operator approval.
3. Add official/developer/governance source packages for the initial desk assets.
4. Add secure source-candidate discovery for newly added Kraken assets.
5. Upgrade community statistics with rolling baselines, sentiment velocity, narrative state, and source diversity.
6. Add event-reaction materialization (5m/15m/30m/1h/4h/24h).
7. Add data-health freshness/conflict controls across all feeds.
8. Expand Floor Catalyst and Risk Radar panels.
9. Add intelligence audit records for shadow strategy comparisons.
10. Accumulate sufficient history, then run baseline vs +macro vs +news vs +community vs +cross-asset ablations.
11. Run out-of-sample validation.
12. Only proven features may be proposed for limited Vector Engine influence.

## Strategy/live status

The Intelligence Expansion does not change the separate strategy-readiness result.
The current strategy has not demonstrated a profitability basis sufficient for live promotion.
Live trading remains blocked. No intelligence feature added in this expansion overrides that.
