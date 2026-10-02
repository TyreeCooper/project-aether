"use client";

import { useEffect, useMemo, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";
const floorPath = process.env.NEXT_PUBLIC_AETHER_FLOOR_PATH || "/api/v1/vnext/floor";
const ingressPath = "/api/v1/vnext/ingress-runtime";
const strategyPath = "/api/v1/vnext/strategy-runtime";
const operatorPath = "/api/v1/vnext/operator";
const discoveryPath = "/api/v1/vnext/discovery-runtime";
const maintenancePath = "/api/v1/vnext/maintenance";

async function getJson(path) {
  const response = await fetch(`${apiBase}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

async function postJson(path, body, operatorToken, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase}${path}`, {
      method: "POST",
      cache: "no-store",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Operator-Token": operatorToken },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.detail || `${response.status} ${path}`);
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`Operation ended after ${Math.round(timeoutMs / 1000)}s without completion.`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function text(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function num(value, digits = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function money(value, fallback = "—") {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  const sign = parsed < 0 ? "-$" : "$";
  return sign + Math.abs(parsed).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function ts(value, fallback = "waiting") {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback;
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

function age(value, nowMs) {
  const stamp = Date.parse(value || "");
  if (!Number.isFinite(stamp)) return "—";
  const seconds = Math.max(0, Math.floor((nowMs - stamp) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function duration(value, nowMs) {
  const stamp = Date.parse(value || "");
  if (!Number.isFinite(stamp)) return "—";
  const seconds = Math.max(0, Math.floor((nowMs - stamp) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

function tone(value) {
  const v = String(value || "").toUpperCase();
  if (["CLEAR","RUNNING","ONLINE","OPEN","READY","GREEN","ACTIVE"].includes(v)) return "good";
  if (["FAULT","BLOCKED","HALT","REJECT","ERROR","OFFLINE"].includes(v)) return "bad";
  if (["DEGRADED","WAIT","WATCH","FIRE","STARTING","SYNCING","BUSY","CATCHING_UP","BASELINE_PENDING","RECOVERY","RECOVERY_BEFORE_BASELINE"].includes(v)) return "warn";
  return "neutral";
}

function Badge({ children, value }) {
  return <span className={`badge ${tone(value ?? children)}`}>{children}</span>;
}

const NAV = [
  ["command", "Command Center", "Overview"],
  ["markets", "Markets", "Provider universe"],
  ["pipeline", "Pipeline", "Flow & diagnostics"],
  ["trading", "Trading Floor", "Opportunities"],
  ["positions", "Positions", "Open risk"],
  ["blotter", "Blotter", "Completed trades"],
  ["maintenance", "Maintenance", "Self-healing"],
  ["settings", "Settings", "Controls"],
];

const PROVIDERS = ["Kraken", "tastyfx", "NinjaTrader", "IBKR"];

function providerRows(discovery) {
  const providers = discovery?.last_result?.providers || {};
  return PROVIDERS.map((provider) => {
    const observed = providers[provider];
    return observed ? { provider, ...observed } : {
      provider,
      status: "NOT OBSERVED",
      reason: "waiting_for_discovery_cycle",
      catalog_count: null,
      eligible_count: null,
      focus_count: null,
      top100: [],
    };
  });
}

function observedSum(values) {
  if (values.some((value) => value === null || value === undefined || !Number.isFinite(Number(value)))) return null;
  return values.reduce((sum, value) => sum + Number(value), 0);
}

function combinedStrategyRows(strategy) {
  const seed = strategy?.last_result?.assets || {};
  const dynamic = strategy?.last_result?.dynamic_assets || {};
  return Object.entries({ ...seed, ...dynamic })
    .map(([assetId, row]) => ({ assetId, ...(row || {}) }))
    .sort((a, b) => {
      const order = { OPEN: 0, FIRE: 1, WATCH: 2, READY: 3, NO_SETUP: 4 };
      return (order[String(a.stage || "").toUpperCase()] ?? 9) - (order[String(b.stage || "").toUpperCase()] ?? 9)
        || a.assetId.localeCompare(b.assetId);
    });
}

function Section({ eyebrow, title, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panelHead">
        <div><span>{eyebrow}</span><h2>{title}</h2></div>
        {action ? <div className="panelAction">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value, sub, state }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong className={state ? `metricValue ${tone(state)}` : "metricValue"}>{value}</strong>
      {sub ? <small>{sub}</small> : null}
    </article>
  );
}

function RuntimeStrip({ floor, ingress, strategy, discovery, maintenance }) {
  const pipeline = maintenance?.last_result?.status || "SYNCING";
  return (
    <div className="runtimeStrip">
      <div><span>BUILD</span><b>{text(floor?.build?.source_revision?.slice(0, 8), "local")}</b></div>
      <div><span>SNAPSHOT</span><b>{text(floor?.snapshot_id, "NOT OBSERVED")}</b></div>
      <div><span>REFRESHED</span><b>{ts(floor?.refresh_time_utc || floor?.as_of_utc, "NOT OBSERVED")}</b></div>
      <div><span>INGRESS</span><Badge value={ingress?.last_error ? "FAULT" : ingress?.running ? "RUNNING" : "WAIT"}>{ingress?.last_error ? "FAULT" : ingress?.running ? "RUNNING" : "WAIT"}</Badge></div>
      <div><span>DISCOVERY</span><Badge value={discovery?.last_error ? "FAULT" : discovery?.running ? "RUNNING" : "WAIT"}>{discovery?.last_error ? "FAULT" : discovery?.running ? "RUNNING" : "WAIT"}</Badge></div>
      <div><span>STRATEGY</span><Badge value={strategy?.last_error ? "FAULT" : strategy?.running ? "RUNNING" : "WAIT"}>{strategy?.last_error ? "FAULT" : strategy?.running ? "RUNNING" : "WAIT"}</Badge></div>
      <div><span>PIPELINE</span><Badge value={pipeline}>{pipeline}</Badge></div>
    </div>
  );
}

function CommandCenter({ floor, ingress, strategy, discovery, operator, maintenance, nowMs }) {
  const universe = floor?.full_universe || [];
  const positions = floor?.open_cockpits || [];
  const providers = providerRows(discovery);
  const catalog = observedSum(providers.map((r) => r.catalog_count));
  const eligible = observedSum(providers.map((r) => r.eligible_count));
  const focusRaw = discovery?.last_result?.focus_admitted_count;
  const focus = focusRaw === null || focusRaw === undefined ? null : Number(focusRaw);
  const pipe = strategy?.last_result?.pipeline || {};
  const strategyRows = combinedStrategyRows(strategy).slice(0, 12);
  const maintenanceState = maintenance?.last_result || {};
  const bank = operator?.bank || {};
  const events = operator?.activity || [];
  return (
    <div className="pageGrid">
      <div className="hero">
        <div>
          <span className="kicker">AETHER SANDBOX OPERATIONS</span>
          <h2>Autonomous market operations console</h2>
          <p>Provider-wide discovery, pipeline state, strategy activity, risk and self-healing in one command surface.</p>
        </div>
        <div className="heroModes">
          <Badge value="GREEN">PAPER ACTIVE</Badge>
          <Badge value="BLOCKED">LIVE BLOCKED</Badge>
          <Badge value={maintenanceState.status || "SYNCING"}>{text(maintenanceState.status, "SYNCING")}</Badge>
        </div>
      </div>

      <div className="metricGrid">
        <Metric label="Catalog instruments" value={catalog === null ? "NOT OBSERVED" : num(catalog)} sub="Across connected provider lanes" />
        <Metric label="Focus admitted" value={focus === null ? "NOT OBSERVED" : num(focus)} sub={eligible === null ? "eligibility NOT OBSERVED" : `${num(eligible)} eligible`} />
        <Metric label="Evaluated this cycle" value={pipe.strategy_evaluated === undefined ? "NOT OBSERVED" : num(pipe.strategy_evaluated)} sub={pipe.market_ready === undefined ? "market readiness NOT OBSERVED" : `${num(pipe.market_ready)} market ready`} />
        <Metric label="Open positions" value={num(positions.length)} sub="PAPER positions" />
        <Metric label="Book cash" value={money(bank.book_cash_usd, "NOT OBSERVED")} sub={bank.cash_reserved_usd === null || bank.cash_reserved_usd === undefined ? "reserved NOT OBSERVED" : `${money(bank.cash_reserved_usd)} reserved`} />
        <Metric label="Maintenance" value={text(maintenanceState.status, "SYNCING")} sub={text(maintenanceState.primary_reason, "establishing baseline")} state={maintenanceState.status} />
      </div>

      <Section eyebrow="PIPELINE" title="Operational flow" action={<span>{text(maintenanceState.first_causal_edge, "No causal clog")}</span>} className="wide">
        <div className="stageRail">
          {(maintenanceState.stages || []).map((row) => (
            <div className="stageNode" key={row.stage}>
              <span>{row.stage.replaceAll("_", " ")}</span>
              <strong>{num(row.pass)}/{num(row.input)}</strong>
              <small>pass / input</small>
            </div>
          ))}
          {!(maintenanceState.stages || []).length ? <div className="empty">Waiting for Maintenance baseline.</div> : null}
        </div>
      </Section>

      <Section eyebrow="OPPORTUNITY TAPE" title="Current strategy activity">
        <div className="dataTable compact">
          <div className="tableHead"><span>Instrument</span><span>Stage</span><span>Reason</span><span>Watch</span></div>
          {strategyRows.length ? strategyRows.map((row) => (
            <div className="tableRow" key={row.assetId}>
              <strong>{row.assetId.toUpperCase()}</strong>
              <Badge value={row.stage}>{text(row.stage, "WAIT")}</Badge>
              <span>{text(row.reason, "—")}</span>
              <span>{row.watch_eligible === true ? "YES" : row.watch_eligible === false ? "NO" : "—"}</span>
            </div>
          )) : <div className="empty">No strategy activity reported yet.</div>}
        </div>
      </Section>

      <Section eyebrow="SYSTEM EVENTS" title="Latest activity">
        <div className="eventList">
          {events.slice(0, 12).map((row) => (
            <div key={row.event_id} className="eventRow">
              <time>{ts(row.created_at_utc, "—")}</time>
              <div><strong>{text(row.seat, "Firm")} · {text(row.new_state, "EVENT")}</strong><span>{text(row.reason_code, "recorded")}</span></div>
            </div>
          ))}
          {!events.length ? <div className="empty">No recorded Firm events yet.</div> : null}
        </div>
      </Section>

      <Section eyebrow="OPEN RISK" title="Active positions" className="wide">
        {positions.length ? <div className="positionGrid">
          {positions.map((row) => <PositionCard row={row} nowMs={nowMs} key={row.position_key} />)}
        </div> : <div className="empty">No open PAPER positions.</div>}
      </Section>
    </div>
  );
}

function Markets({ discovery, ingress, nowMs }) {
  const [filter, setFilter] = useState("");
  const rows = providerRows(discovery);
  const quotes = ingress?.last_result?.quotes || [];
  const quoteMap = Object.fromEntries(quotes.map((q) => [String(q.symbol || "").toUpperCase(), q]));
  return (
    <div className="pageGrid">
      <div className="pageIntro">
        <div><span className="kicker">MARKET INTELLIGENCE</span><h2>Provider universe</h2><p>Full catalog visibility with provider-level ranking. Priority lists are scheduling signals, not trade permission.</p></div>
        <input className="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter instruments…" />
      </div>
      {rows.map((row) => {
        const items = (row.top100 || []).filter((item) => !filter || String(item.symbol || "").toLowerCase().includes(filter.toLowerCase()));
        return (
          <Section
            eyebrow={row.catalog_mode === "provider_native" ? "NATIVE CATALOG" : "REFERENCE CATALOG"}
            title={row.provider}
            action={<Badge value={row.status === "online" ? "ONLINE" : "FAULT"}>{String(row.status || "waiting").toUpperCase()}</Badge>}
            className="wide"
            key={row.provider}
          >
            <div className="providerStats">
              <Metric label="Catalog" value={num(row.catalog_count)} />
              <Metric label="Eligible" value={num(row.eligible_count)} />
              <Metric label="Priority pool" value={num(row.focus_count)} />
              <Metric label="Data mode" value={text(row.catalog_mode, "reference").replaceAll("_", " ")} />
            </div>
            <div className="marketTable">
              <div className="marketHead"><span>Rank</span><span>Instrument</span><span>Score</span><span>Move</span><span>Reference</span><span>Quote age</span><span>Readiness</span></div>
              {items.map((item) => {
                const q = quoteMap[String(item.symbol || "").toUpperCase()] || quoteMap[String(item.market_data_symbol || "").toUpperCase()];
                return (
                  <div className="marketRow" key={`${row.provider}:${item.market_data_symbol || item.symbol}`}>
                    <span>#{num(item.rank)}</span>
                    <strong>{text(item.symbol)}</strong>
                    <span>{num(item.score, 1)}</span>
                    <span className={Number(item.change_pct) < 0 ? "loss" : Number(item.change_pct) > 0 ? "gain" : ""}>{Number(item.change_pct) >= 0 ? "+" : ""}{num(item.change_pct, 2)}%</span>
                    <span>{money(item.price)}</span>
                    <span>{age(q?.reference_ts_utc, nowMs)}</span>
                    <Badge value="ACTIVE">PRIORITY</Badge>
                  </div>
                );
              })}
              {!items.length ? <div className="empty">{row.status === "online" ? "No matching instruments." : text(row.reason, "Provider data unavailable.")}</div> : null}
            </div>
          </Section>
        );
      })}
    </div>
  );
}

function floorQueueCount(floor, seat, state) {
  const row = (floor?.seat_queues || []).find((item) => item.seat === seat && item.state === state);
  return row ? Number(row.count || 0) : null;
}

const PIPELINE_TRUE_PREDICATES = {
  CATALOG: "eligible provider row → FOCUS_ADMITTED; provider rank is priority telemetry, not execution permission",
  FOCUS_ADMITTED: "projection.product != null && runtime_playbook_for_product(...) succeeds",
  PRODUCT_BOUND: "priority OPEN assets + rotating slice; capacity = max(batch_size - priority_count, 0)",
  ROAMING_SCAN: "binding_blockers == () && product.market_data_ready() && lifecycle_fire_eligible() && decision-time observation is valid",
  MARKET_READY: "history.error is None && source-bound warm-up snapshot assembles successfully",
  HISTORY_READY: "completed trigger bar closes at/before as_of_utc && setup identity has not already completed",
  STRATEGY_EVALUATED: "plan.eligible === true → WATCH; otherwise terminal NO_SETUP evidence",
  WATCH: "state==WATCH && completed_bar matches trigger/grain && !invalidation_hit && market healthy && side supported && stop legal",
  FIRE: "RiskSizeResult.ok && quantity > 0 after trade/asset/cluster/portfolio + product/capital quantity caps",
  SIZE: "product_side_supported(...) && ready_after_cost_hurdle(opportunity_pct, modeled_round_trip_cost)",
  READY: "READY identity/preflight valid && Governor clear && Firm risk/capital reservation succeeds atomically",
  RESERVED: "PAPER_ONLY && LIVE_BLOCKED && intent.state==RESERVED && order_type==MARKET_PAPER && OPEN risk reservation exists",
  SUBMITTED: "at_utc >= paper_fill_due_at(...) && fill_time_reject_code(...) is None",
  OPEN: "governor_halted || hard_stop_on_bid/ask || completed_structure_close < frozen_breakout || as_of_utc >= time_stop_deadline",
  EXIT_REQUESTED: "active EXIT_PRECEDENCE reason + OPEN trade + matching market observation → FLATTEN_REQUEST",
  CLOSE_RESERVED: "matching FLATTEN_REQUEST && OPEN trade && zero-capital CLOSE reservation",
  CLOSE_SUBMITTED: "CLOSE intent state==RESERVED && MARKET_PAPER && reserved_cash_usd==0 && reserved_margin_usd==0",
  FLAT: "SUBMITTED CLOSE passes paper latency + fresh executable market guard → FILLED → finalize_filled_flat()",
};

function reasonHistogram(rows, predicate = () => true) {
  const counts = new Map();
  for (const row of rows || []) {
    if (!row || !predicate(row)) continue;
    const reason = text(row.reason || row.reject_code || row.error || row.first_blocker_reason, "unspecified");
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([reason, count]) => ({ reason, count }));
}

function reconcileGate({ input, pass, wait, reject, bypass = 0, fault = 0, exact = false, reasons = [] }) {
  const values = [input, pass, wait, reject, bypass, fault];
  const numeric = values.every((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
  if (!numeric) {
    return { input, pass, wait, reject, bypass, fault, unexplained: null, reconciled: null, coverage: "PARTIAL", reasons };
  }
  const accounted = Number(pass) + Number(wait) + Number(reject) + Number(bypass) + Number(fault);
  const unexplained = Math.max(0, Number(input) - accounted);
  return {
    input: Number(input), pass: Number(pass), wait: Number(wait), reject: Number(reject),
    bypass: Number(bypass), fault: Number(fault), unexplained,
    reconciled: exact ? accounted === Number(input) : null,
    coverage: exact ? "FULL" : "PARTIAL",
    reasons,
  };
}

const PIPELINE_GATE_BLUEPRINT = [
  {
    stage: "CATALOG",
    label: "Provider Catalog",
    owner: "Discovery",
    gate: "Discovery eligibility & focus admission",
    plain: "Provider rows must survive catalog eligibility and enter the prioritized focus pool. Rank controls attention order; it is not permission to trade.",
    dev: 'provider_focus_handoff.focus_handoff_rows() → state="FOCUS_ADMITTED"; provider rank remains priority telemetry, not an execution veto.',
  },
  {
    stage: "FOCUS_ADMITTED",
    label: "Focus Admitted",
    owner: "Discovery → Runtime",
    gate: "Runtime product commissioning",
    plain: "The instrument needs a real runtime product definition and a commissioned strategy contract before it can enter deep evaluation.",
    dev: 'prototype_strategy_supervisor._sync_dynamic_kraken_products() + runtime_playbook_for_product(..., playbook_id="pb_crypto_swing_v1_2").',
  },
  {
    stage: "PRODUCT_BOUND",
    label: "Product Bound",
    owner: "Runtime Registry",
    gate: "Roaming scheduler",
    plain: "Commissioned products are scheduled into the active scan slice. Open positions are always retained; otherwise the scheduler rotates through the eligible set.",
    dev: "prototype_strategy_supervisor._rotating_dynamic_strategy_batch(... configured_dynamic_strategy_scan_batch_size()); current default batch=4, configured range=1..20.",
  },
  {
    stage: "ROAMING_SCAN",
    label: "Roaming Scan",
    owner: "Strategy Supervisor",
    gate: "Executable market ingress",
    plain: "The product must have executable market plumbing, valid lifecycle/calendar state, a usable quote and a decision-time clock that is not invalid.",
    dev: "market_ingress.ingest_market_quotes() → binding_blockers(), ProductRegistryRow.market_data_ready(), lifecycle_fire_eligible(); then _partition_observations_for_decision_time().",
  },
  {
    stage: "MARKET_READY",
    label: "Market Ready",
    owner: "Market Ingress",
    gate: "History & warm-up completeness",
    plain: "A current quote is not enough. The strategy requires enough completed history to build its source-bound feature snapshot before evaluation.",
    dev: "prototype_strategy_supervisor._fetch_dynamic_strategy_history() → assemble_prototype_crypto_warmup(). Current crypto warm-up uses Coinbase/Kraken history and supplies btc_kraken_daily regime context.",
  },
  {
    stage: "HISTORY_READY",
    label: "History Ready",
    owner: "History / Features",
    gate: "Closed-bar strategy evaluation",
    plain: "Only a completed decision bar may trigger evaluation. The current crypto path requires the exact completed 1-hour Kraken bar, rejects future/unavailable bars and will not re-enter an already-traded setup.",
    dev: "prototype_crypto_entry_runtime._require_completed_kraken_hour() + build_prototype_crypto_entry_plan(); prototype_strategy_supervisor._setup_already_completed().",
  },
  {
    stage: "STRATEGY_EVALUATED",
    label: "Strategy Evaluated",
    owner: "Strategy",
    gate: "Scout setup admission",
    plain: "The evaluated strategy must actually produce a WATCH candidate. A valid evaluation with no setup is a normal no-trade outcome, not a broken pipeline.",
    dev: "advance_prototype_crypto_entry(): if !plan.eligible → NO_SETUP; runtime_scout_bridge.persist_cycle_watch_setups() persists only cycle.decision.watch_candidates.",
  },
  {
    stage: "WATCH",
    label: "WATCH",
    owner: "Scout",
    gate: "Sniper FIRE validation",
    plain: "The setup must still match the completed trigger bar, remain uninvalidated, have usable current market data, support the requested side and carry a legal protective stop.",
    dev: "sniper.evaluate_sniper_fire(); VNextStore.record_sniper_ticket() also rejects duplicate signal_key, BENCH/DISABLED route state and Governor admission blocks.",
  },
  {
    stage: "FIRE",
    label: "FIRE",
    owner: "Sniper",
    gate: "Firm Risk sizing",
    plain: "Risk sizes the trade against current Firm equity and the combined open + pending exposure. A candidate cannot consume more than the frozen trade, asset, cluster or portfolio capacity.",
    dev: "runtime_risk_bridge.size_runtime_fire_ticket() → VNextStore.size_fire_ticket() → risk.size_candidate_to_risk(); ceilings: trade 0.75%, asset 1.50%, cluster 2.25%, portfolio 3.00%.",
  },
  {
    stage: "SIZE",
    label: "SIZE",
    owner: "Risk",
    gate: "Clerk economics",
    plain: "The Risk-sized candidate must have a supported side and enough expected opportunity to clear modeled round-trip costs. Clerk cannot increase the Risk quantity.",
    dev: "runtime_clerk_bridge.evaluate_and_persist_clerk_ready() → clerk.evaluate_clerk_ready(); current crypto path passes PROTOTYPE_COST_EDGE_MULTIPLE=1.40.",
  },
  {
    stage: "READY",
    label: "READY",
    owner: "Clerk",
    gate: "Portfolio atomic reservation",
    plain: "Before an order exists, Portfolio rechecks identity, product binding, Governor state and Firm risk capacity, then atomically reserves the OPEN intent so concurrent candidates cannot spend the same capacity.",
    dev: "runtime_portfolio_bridge.reserve_runtime_ready_ticket() → VNextStore.reserve_risk_checked_open_intent(); idempotency + active-book and RESERVED/SUBMITTED risk are checked under the Firm guard row.",
  },
  {
    stage: "RESERVED",
    label: "RESERVED",
    owner: "Portfolio",
    gate: "PAPER submit",
    plain: "The reserved intent can submit only through the PAPER adapter. It must still be a MARKET_PAPER OPEN intent with an existing Firm risk reservation.",
    dev: "runtime_execution_bridge.submit_runtime_reserved_open(); requires PAPER_ONLY && LIVE_BLOCKED, state=RESERVED, order_type=MARKET_PAPER and tracked risk reservation.",
  },
  {
    stage: "SUBMITTED",
    label: "SUBMITTED",
    owner: "Paper Execution",
    gate: "Fill-time market guard",
    plain: "Submission does not guarantee a fill. The later fill cycle waits for paper latency and rechecks market quality, freshness, session, spread expansion and protective-stop geometry.",
    dev: "runtime_fill_bridge.fill_runtime_submitted_open() → execution.fill_submitted_paper_intent(); 250ms latency, spread ≤ 2× READY spread, stop not breached, no bad_fill_through_stop.",
  },
  {
    stage: "OPEN",
    label: "OPEN",
    owner: "Position Management",
    gate: "Exit management",
    plain: "An open position remains managed regardless of discovery rank. Exit logic evaluates the position from current market and completed-bar state; a failed close does not make the position disappear.",
    dev: "prototype_crypto_exit_runtime.advance_prototype_crypto_exit(); close lifecycle continues through runtime_exit_request_bridge / runtime_close_reserve_bridge / runtime_close_execution_bridge / runtime_close_fill_bridge.",
  },
  {
    stage: "EXIT_REQUESTED",
    label: "Flatten Requested",
    owner: "Exit",
    gate: "Close reservation",
    plain: "A valid exit reason is persisted as FLATTEN_REQUEST. The position is still OPEN until the close lifecycle actually succeeds.",
    dev: "runtime_exit_request_bridge.request_runtime_flatten() validates EXIT_PRECEDENCE, OPEN trade identity and observation identity before persisting FLATTEN_REQUEST.",
  },
  {
    stage: "CLOSE_RESERVED",
    label: "Close Reserved",
    owner: "Portfolio",
    gate: "Paper close submit",
    plain: "The risk-reducing close must map to the still-open trade and matching FLATTEN_REQUEST. It reserves zero new cash and zero new margin.",
    dev: "runtime_close_reserve_bridge.reserve_runtime_flatten() requires matching FLATTEN_REQUEST and OPEN trade identity; reserve_cash_usd=0 and reserve_margin_usd=0.",
  },
  {
    stage: "CLOSE_SUBMITTED",
    label: "Close Submitted",
    owner: "Paper Execution",
    gate: "Close fill-time guard",
    plain: "The submitted close waits for paper latency and must still have fresh executable market data. A rejected close leaves the trade OPEN for a later retry with new market evidence.",
    dev: "runtime_close_execution_bridge.submit_runtime_reserved_close() → runtime_close_fill_bridge.fill_runtime_submitted_close(); rejection releases the reservation and prototype_crypto_exit_runtime returns OPEN.",
  },
  {
    stage: "FLAT",
    label: "FLAT / BLOTTER",
    owner: "Book of Record",
    gate: null,
    plain: "Completed round trips land in the blotter and evidence surfaces with execution economics and exit reason.",
    dev: "Terminal close persistence feeds the durable book / blotter; this is the end of the entry-to-close path shown here.",
  },
];

function Pipeline({ strategy, discovery, ingress, maintenance, floor, operator }) {
  const pipe = strategy?.last_result?.pipeline || {};
  const registry = strategy?.last_result?.dynamic_product_registry || {};
  const queue = (seat, state) => floorQueueCount(floor, seat, state);
  const counts = {
    CATALOG: observedSum(providerRows(discovery).map((row) => row.catalog_count)),
    FOCUS_ADMITTED: discovery?.last_result?.focus_admitted_count === undefined ? null : Number(discovery.last_result.focus_admitted_count),
    PRODUCT_BOUND: registry.persisted === undefined || registry.persisted === null ? null : Number(registry.persisted),
    ROAMING_SCAN: pipe.roaming_batch === undefined ? null : Number(pipe.roaming_batch || 0),
    MARKET_READY: pipe.market_ready === undefined ? null : Number(pipe.market_ready || 0),
    HISTORY_READY: pipe.history_ready === undefined ? null : Number(pipe.history_ready || 0),
    STRATEGY_EVALUATED: pipe.strategy_evaluated === undefined ? null : Number(pipe.strategy_evaluated || 0),
    WATCH: queue("Scout", "WATCH") ?? (pipe.watch === undefined ? null : Number(pipe.watch || 0)),
    FIRE: queue("Sniper", "FIRE"),
    SIZE: queue("Risk", "SIZE"),
    READY: queue("Clerk", "READY"),
    RESERVED: queue("Portfolio", "ORDER"),
    SUBMITTED: null,
    OPEN: Array.isArray(floor?.open_cockpits) ? floor.open_cockpits.length : null,
    FLAT: Array.isArray(operator?.blotter) ? operator.blotter.length : null,
  };
  const exitRows = Object.values(strategy?.last_result?.exit_results || {});
  counts.EXIT_REQUESTED = null;
  counts.CLOSE_RESERVED = null;
  counts.CLOSE_SUBMITTED = exitRows.length ? exitRows.filter((row) => row?.stage === "CLOSE_SUBMITTED").length : null;
  const cycleFlat = exitRows.filter((row) => row?.stage === "FLAT").length;
  if (cycleFlat > 0) counts.FLAT = cycleFlat;

  const catalog = counts.CATALOG;
  const eligible = providerRows(discovery).reduce((sum, row) => sum + Number(row.eligible_count || 0), 0);
  const dynamicRows = Object.values(strategy?.last_result?.dynamic_assets || {});
  const ingressRows = ingress?.last_result?.asset_results || [];
  const queueRows = floor?.seat_queues || [];

  const gateTelemetry = (stage) => {
    if (stage === "CATALOG") {
      return reconcileGate({
        input: catalog,
        pass: counts.FOCUS_ADMITTED,
        wait: Math.max(0, eligible - counts.FOCUS_ADMITTED),
        reject: Math.max(0, catalog - eligible),
        exact: catalog >= eligible && eligible >= counts.FOCUS_ADMITTED,
        reasons: reasonHistogram(providerRows(discovery).filter((row) => row.status !== "online"), () => true),
      });
    }
    if (stage === "ROAMING_SCAN") {
      return reconcileGate({
        input: counts.ROAMING_SCAN,
        pass: counts.MARKET_READY,
        wait: Number(pipe.market_not_ready || 0),
        reject: 0,
        exact: pipe.market_not_ready !== undefined,
        reasons: reasonHistogram(dynamicRows, (row) => row?.stage === "MARKET_NOT_READY").concat(
          reasonHistogram(ingressRows, (row) => row?.executable === false)
        ).slice(0, 6),
      });
    }
    if (stage === "MARKET_READY") {
      return reconcileGate({
        input: counts.MARKET_READY,
        pass: counts.HISTORY_READY,
        wait: Number(pipe.history_not_ready || 0),
        reject: 0,
        exact: pipe.history_not_ready !== undefined,
        reasons: reasonHistogram(dynamicRows, (row) => row?.stage === "HISTORY_NOT_READY"),
      });
    }
    if (stage === "HISTORY_READY") {
      return reconcileGate({
        input: counts.HISTORY_READY,
        pass: counts.STRATEGY_EVALUATED,
        wait: 0,
        reject: 0,
        fault: Number(pipe.evaluation_error || 0),
        exact: pipe.evaluation_error !== undefined,
        reasons: reasonHistogram(dynamicRows, (row) => ["EVALUATION_ERROR", "PIPELINE_ERROR"].includes(row?.stage)),
      });
    }
    if (stage === "STRATEGY_EVALUATED") {
      const qualified = Number(pipe.watch || 0) + Number(pipe.fire_or_beyond || 0);
      const noSetup = dynamicRows.filter((row) => row?.stage === "NO_SETUP").length;
      return reconcileGate({
        input: counts.STRATEGY_EVALUATED,
        pass: qualified,
        wait: 0,
        reject: noSetup,
        exact: counts.STRATEGY_EVALUATED === qualified + noSetup,
        reasons: reasonHistogram(dynamicRows, (row) => row?.stage === "NO_SETUP"),
      });
    }
    if (stage === "OPEN" && exitRows.length) {
      const pass = exitRows.filter((row) => ["CLOSE_SUBMITTED", "FLAT"].includes(row?.stage)).length;
      const wait = exitRows.filter((row) => row?.stage === "OPEN").length;
      return reconcileGate({
        input: exitRows.length,
        pass,
        wait,
        reject: 0,
        exact: pass + wait === exitRows.length,
        reasons: reasonHistogram(exitRows),
      });
    }
    const seatByStage = {
      WATCH: ["Scout", "WATCH"],
      FIRE: ["Sniper", "FIRE"],
      SIZE: ["Risk", "SIZE"],
      READY: ["Clerk", "READY"],
      RESERVED: ["Portfolio", "ORDER"],
    };
    const seat = seatByStage[stage];
    if (seat) {
      const matching = queueRows.filter((row) => row.seat === seat[0] && row.state === seat[1]);
      return reconcileGate({
        input: counts[stage],
        pass: null,
        wait: matching.reduce((sum, row) => sum + Number(row.count || 0), 0),
        reject: null,
        exact: false,
        reasons: reasonHistogram(matching, (row) => Number(row.blocker_count || 0) > 0),
      });
    }
    return reconcileGate({ input: counts[stage], pass: null, wait: null, reject: null, exact: false, reasons: [] });
  };

  const telemetryByStage = Object.fromEntries(
    PIPELINE_GATE_BLUEPRINT.map((item) => [item.stage, gateTelemetry(item.stage)])
  );
  const fullCoverage = Object.values(telemetryByStage).filter((row) => row.coverage === "FULL").length;
  const unexplainedTotal = Object.values(telemetryByStage).reduce(
    (sum, row) => sum + (row.unexplained === null ? 0 : Number(row.unexplained || 0)),
    0
  );
  const m = maintenance?.last_result || {};
  const firstCausal = String(m.first_causal_edge || "").toUpperCase();

  return (
    <div className="pageGrid">
      <div className="pageIntro">
        <div>
          <span className="kicker">STATE MACHINE / CODE-BOUND</span>
          <h2>Institutional pipeline flow map</h2>
          <p>Top-to-bottom lifecycle. Every connector describes the actual gate that advances, waits or rejects an instrument, with the corresponding implementation path shown directly underneath.</p>
        </div>
        <Badge value={m.status}>{text(m.status, "SYNCING")}</Badge>
      </div>

      <Section eyebrow="FIRST CAUSAL CLOG" title={text(m.first_causal_edge, "No causal clog identified")} className="wide">
        <div className="causalBanner">
          <div><span>Status</span><Badge value={m.status}>{text(m.status, "SYNCING")}</Badge></div>
          <div><span>Owner</span><strong>{text(m.owner)}</strong></div>
          <div><span>Affected</span><strong>{num(m.affected_count)}</strong></div>
          <div><span>Reason</span><strong>{text(m.primary_reason)}</strong></div>
          <div><span>Confidence</span><strong>{text(m.confidence)}</strong></div>
        </div>
        <p className="causalObservation">{text(m.observed, "Maintenance is establishing the healthy-system baseline.")}</p>
      </Section>

      <Section eyebrow="ENGINEERING CONSTRAINTS" title="Runtime facts this map will not hide" className="wide">
        <div className="constraintGrid">
          <div><span>Scan scheduler</span><strong>Default batch 4 · configured range 1–20</strong><small>Runtime-selected value is not currently exposed by telemetry.</small></div>
          <div><span>Crypto regime input</span><strong>btc_kraken_daily still exists in warm-up</strong><small>This is a real code dependency to remove/generalize later, not a UI preference.</small></div>
          <div><span>Telemetry coverage</span><strong>{fullCoverage}/{PIPELINE_GATE_BLUEPRINT.length} gates fully reconcilable</strong><small>Unknown outcomes stay NOT OBSERVED; the UI does not invent zeroes.</small></div>
          <div className={unexplainedTotal ? "constraintFault" : ""}><span>Unexplained flow loss</span><strong>{num(unexplainedTotal)}</strong><small>{unexplainedTotal ? "Observed counts do not reconcile at one or more fully measured gates." : "No unexplained loss in fully measured gates."}</small></div>
        </div>
      </Section>

      <Section eyebrow="FLOW MAP" title="Canonical sandbox lifecycle" className="wide">
        <div className="verticalFlow">
          {PIPELINE_GATE_BLUEPRINT.map((item, index) => {
            const value = counts[item.stage];
            const observed = value !== null && value !== undefined;
            const flagged = firstCausal.includes(item.stage.replaceAll("_", " ")) || firstCausal.includes(item.stage);
            const gate = telemetryByStage[item.stage];
            return (
              <div className="flowUnit" key={item.stage}>
                <article className={flagged ? "flowStageV flagged" : "flowStageV"}>
                  <div className="flowStageIndex">{String(index + 1).padStart(2, "0")}</div>
                  <div className="flowStageBody">
                    <div className="flowStageTitle">
                      <div><span>{item.owner}</span><h3>{item.label}</h3></div>
                      <div className="flowStageCount">
                        <strong>{observed ? num(value) : "—"}</strong>
                        <small>{observed ? "CURRENTLY OBSERVED" : "NOT EXPOSED BY CURRENT TELEMETRY"}</small>
                      </div>
                    </div>
                    {item.stage === "RESERVED" ? <p className="telemetryNote">Floor currently projects this queue as <code>Portfolio / ORDER</code>; the underlying runtime transition is READY → RESERVED.</p> : null}
                    {item.stage === "SUBMITTED" ? <p className="telemetryNote">The current Floor payload does not expose a dedicated SUBMITTED count, so this map intentionally shows no fabricated number.</p> : null}
                    {["EXIT_REQUESTED","CLOSE_RESERVED"].includes(item.stage) ? <p className="telemetryNote">This transient close state is enforced in code but is not separately counted in the current Floor payload.</p> : null}
                  </div>
                </article>

                {item.gate ? (
                  <div className="flowConnector">
                    <div className="flowArrow" aria-hidden="true"><span>↓</span></div>
                    <article className="flowGateCard">
                      <div className="flowGateHead">
                        <span>GATE {String(index + 1).padStart(2, "0")}</span>
                        <strong>{item.gate}</strong>
                        <div className="gateOutcomes"><b>PASS ↓</b><b>WAIT ↺</b><b>REJECT → EVIDENCE</b></div>
                      </div>
                      <div className="gateExplanation">
                        <div>
                          <span>PLAIN ENGLISH</span>
                          <p>{item.plain}</p>
                        </div>
                        <div className="devNote">
                          <span>DEV CODE NOTE</span>
                          <code>{item.dev}</code>
                        </div>
                      </div>
                      <div className="predicateNote">
                        <span>TRUE CODE PREDICATE</span>
                        <code>{PIPELINE_TRUE_PREDICATES[item.stage]}</code>
                      </div>
                      <div className="gateTelemetry">
                        <div><span>INPUT</span><strong>{gate.input === null || gate.input === undefined ? "—" : num(gate.input)}</strong></div>
                        <div><span>PASS</span><strong>{gate.pass === null || gate.pass === undefined ? "—" : num(gate.pass)}</strong></div>
                        <div><span>WAIT</span><strong>{gate.wait === null || gate.wait === undefined ? "—" : num(gate.wait)}</strong></div>
                        <div><span>REJECT / NO SETUP</span><strong>{gate.reject === null || gate.reject === undefined ? "—" : num(gate.reject)}</strong></div>
                        <div><span>FAULT</span><strong>{gate.fault === null || gate.fault === undefined ? "—" : num(gate.fault)}</strong></div>
                        <div><span>UNEXPLAINED</span><strong className={Number(gate.unexplained || 0) > 0 ? "loss" : ""}>{gate.unexplained === null ? "—" : num(gate.unexplained)}</strong></div>
                        <div><span>COVERAGE</span><strong>{gate.coverage}</strong></div>
                        <div><span>RECONCILED</span><strong>{gate.reconciled === null ? "NOT OBSERVED" : gate.reconciled ? "YES" : "NO"}</strong></div>
                      </div>
                      <div className="gateReasons">
                        <span>LIVE REASON DISTRIBUTION</span>
                        <div>
                          {gate.reasons.length ? gate.reasons.map((row) => <b key={`${item.stage}:${row.reason}`}><i>{row.count}</i>{row.reason}</b>) : <em>Reason histogram not exposed for this gate.</em>}
                        </div>
                      </div>
                    </article>
                    <div className="flowArrow flowArrowBottom" aria-hidden="true"><span>↓</span></div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </Section>

      <Section eyebrow="CURRENT QUEUE PRESSURE" title="Seat-level runtime telemetry" className="wide">
        <div className="queueTable">
          {(floor?.seat_queues || []).map((q) => (
            <div className="queueRow" key={`${q.seat}:${q.state}`}>
              <strong>{q.seat}</strong><span>{q.state}</span><span>{num(q.count)} queued</span><span>{num(q.blocker_count)} blockers</span><small>{text(q.first_blocker_reason, "clear")}</small>
            </div>
          ))}
          {!(floor?.seat_queues || []).length ? <div className="empty">No queue pressure reported.</div> : null}
        </div>
      </Section>
    </div>
  );
}

function TradingFloor({ strategy }) {
  const rows = combinedStrategyRows(strategy);
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">OPPORTUNITY ENGINE</span><h2>Trading floor</h2><p>Live strategy state across every instrument currently reported by the sandbox runtime. No instrument is privileged in the presentation layer.</p></div></div>
      <Section eyebrow="STRATEGY MATRIX" title="Current opportunity states" className="wide">
        <div className="tradeMatrix">
          <div className="tradeHead"><span>Instrument</span><span>Stage</span><span>Reason</span><span>Trigger</span><span>Vol</span><span>Watch</span></div>
          {rows.map((row) => (
            <div className="tradeRow" key={row.assetId}>
              <strong>{row.assetId.toUpperCase()}</strong>
              <Badge value={row.stage}>{text(row.stage, "WAIT")}</Badge>
              <span>{text(row.reason)}</span>
              <span>{ts(row.trigger_close_utc, "—")}</span>
              <span>{num(row.volatility_percentile, 2)}</span>
              <span>{row.watch_eligible === true ? "YES" : row.watch_eligible === false ? "NO" : "—"}</span>
            </div>
          ))}
          {!rows.length ? <div className="empty">Waiting for strategy state.</div> : null}
        </div>
      </Section>
    </div>
  );
}

function PositionCard({ row, nowMs }) {
  return (
    <article className="positionCard">
      <div className="positionTop"><div><strong>{text(row.asset_id).toUpperCase()}</strong><span>{text(row.horizon)} · {text(row.side)}</span></div><Badge value="OPEN">OPEN</Badge></div>
      <div className="positionPnl">{duration(row.opened_at_utc, nowMs)}</div>
      <dl>
        <div><dt>Qty</dt><dd>{num(row.quantity, 8)}</dd></div>
        <div><dt>Entry</dt><dd>{num(row.average_entry_price, 8)}</dd></div>
        <div><dt>Mark</dt><dd>{num(row.mark_price, 8)}</dd></div>
        <div><dt>Stop</dt><dd>{num(row.hard_stop_price, 8)}</dd></div>
      </dl>
    </article>
  );
}

function Positions({ floor, nowMs }) {
  const rows = floor?.open_cockpits || [];
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">OPEN RISK</span><h2>Positions</h2><p>Active PAPER positions remain managed regardless of discovery rank changes.</p></div></div>
      <Section eyebrow="POSITION BOOK" title={`${rows.length} open`} className="wide">
        {rows.length ? <div className="positionGrid">{rows.map((row)=><PositionCard row={row} nowMs={nowMs} key={row.position_key} />)}</div> : <div className="empty">No open positions.</div>}
      </Section>
    </div>
  );
}

function Blotter({ operator }) {
  const rows = operator?.blotter || [];
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">EXECUTION HISTORY</span><h2>Blotter</h2><p>Completed PAPER round trips with cost and excursion telemetry.</p></div></div>
      <Section eyebrow="TRADE LEDGER" title={`${rows.length} completed`} className="wide">
        <div className="blotterTable">
          <div className="blotterHead"><span>Closed</span><span>Instrument</span><span>Side</span><span>Qty</span><span>Entry</span><span>Exit</span><span>Net</span><span>MFE</span><span>MAE</span><span>Reason</span></div>
          {rows.map((row)=>(
            <div className="blotterRow" key={row.trade_id}>
              <span>{ts(row.closed_at_utc,"—")}</span><strong>{text(row.asset_id).toUpperCase()}</strong><span>{text(row.side)}</span><span>{num(row.quantity,8)}</span><span>{num(row.avg_entry_price,8)}</span><span>{num(row.exit_price,8)}</span><span className={Number(row.net_pnl_usd)<0?"loss":Number(row.net_pnl_usd)>0?"gain":""}>{money(row.net_pnl_usd)}</span><span>{money(row.mfe_usd)}</span><span>{money(row.mae_usd)}</span><span>{text(row.exit_reason)}</span>
            </div>
          ))}
          {!rows.length ? <div className="empty">No completed trades in this sandbox session.</div> : null}
        </div>
      </Section>
    </div>
  );
}

function Maintenance({ maintenance }) {
  const m = maintenance?.last_result || {};
  const incidents = maintenance?.incidents || [];
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">SELF-HEALING OPERATIONS</span><h2>Maintenance</h2><p>Expected vs observed system behavior, first-cause diagnosis, incident recurrence and repair evidence.</p></div><Badge value={m.status}>{text(m.status, "SYNCING")}</Badge></div>
      <div className="metricGrid">
        <Metric label="Status" value={text(m.status,"SYNCING")} state={m.status} />
        <Metric label="Mode" value={text(m.maintenance_mode, "BASELINE PENDING")} state={m.maintenance_mode} />
        <Metric label="Healthy baseline" value={maintenance?.healthy_baseline_established || m.healthy_baseline_established ? "ESTABLISHED" : "PENDING"} state={maintenance?.healthy_baseline_established || m.healthy_baseline_established ? "GREEN" : "BUSY"} />
        <Metric label="First causal edge" value={text(m.first_causal_edge,"waiting")} />
        <Metric label="Affected" value={num(m.affected_count)} />
        <Metric label="Confidence" value={text(m.confidence)} />
        <Metric label="Auto-fix" value={m.auto_fix_available ? "AVAILABLE" : "NONE"} state={m.auto_fix_available ? "WARN" : "CLEAR"} />
        <Metric label="Quarantined" value={num((m.quarantined_symbols||[]).length)} />
      </div>
      <Section eyebrow="DIAGNOSIS" title={text(m.primary_reason, "No active diagnosis")}>
        <p className="longText">{text(m.observed, "Waiting for diagnostic cycle.")}</p>
        <div className="detailGrid">
          <div><span>Expected</span><strong>{text(m.expected)}</strong></div>
          <div><span>Owner</span><strong>{text(m.owner)}</strong></div>
          <div><span>Recommended</span><strong>{text(m.recommended_action)}</strong></div>
          <div><span>Repair result</span><strong>{text(m.repair?.result, "NO ACTION")}</strong></div>
        </div>
      </Section>
      <Section eyebrow="INCIDENT HISTORY" title="Recurring faults" className="wide">
        <div className="incidentTable">
          {incidents.map((row)=>(
            <div className="incidentRow" key={row.incident_id}>
              <span>{ts(row.last_seen_at_utc,"—")}</span><Badge value={row.status}>{row.status}</Badge><strong>{row.stage}</strong><span>{row.reason}</span><span>{num(row.affected_count)} affected</span><span>{num(row.recurrence_count)}×</span>
            </div>
          ))}
          {!incidents.length ? <div className="empty">No maintenance incidents recorded.</div> : null}
        </div>
      </Section>
    </div>
  );
}

function Settings({ ingress, strategy, discovery, floor, maintenance, onToggle, onRepair, busy, error }) {
  const [token, setToken] = useState("");
  const controls = maintenance?.controls || {};
  const labels = maintenance?.control_labels || {};
  const unlocked = token.trim().length > 0;
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">SYSTEM CONFIGURATION</span><h2>Settings</h2><p>Operational controls only. PAPER execution and LIVE hard block remain locked outside this UI.</p></div></div>
      <Section eyebrow="RUNTIME" title="Sandbox configuration" className="wide">
        <div className="settingsMetrics">
          <Metric label="Execution" value="PAPER" state="GREEN" sub="Continuous sandbox flow" />
          <Metric label="Live" value="BLOCKED" state="BLOCKED" sub="Not configurable here" />
          <Metric label="Ingress cadence" value={`${num(ingress?.interval_seconds)}s`} />
          <Metric label="Strategy cadence" value={`${num(strategy?.interval_seconds)}s`} />
          <Metric label="Discovery" value={discovery?.running ? "RUNNING" : "WAIT"} state={discovery?.running ? "GREEN":"WARN"} />
          <Metric label="Build" value={text(floor?.build?.source_revision?.slice(0,8),"local")} />
        </div>
      </Section>
      <Section eyebrow="MAINTENANCE AUTHORITY" title="Agent controls" className="wide">
        <label className="tokenField"><span>Operator token</span><input type="password" value={token} onChange={(e)=>setToken(e.target.value)} placeholder="Required to change agent authority" /></label>
        <div className="controlGrid">
          {Object.entries(labels).map(([key,label])=>{
            const enabled = controls[key] !== false;
            return (
              <article className="controlCard" key={key}>
                <div><span>{label}</span><small>{key.replaceAll("_"," ")}</small></div>
                <button type="button" className={enabled?"toggle on":"toggle"} disabled={!unlocked||busy} onClick={()=>onToggle(key,!enabled,token)}><i />{enabled?"ON":"OFF"}</button>
              </article>
            );
          })}
        </div>
        <div className="repairConsole">
          <div className="repairActionRow">
            <button
              type="button"
              className={busy ? "repairButton busy" : "repairButton"}
              disabled={!unlocked||busy||controls.master_enabled===false}
              onClick={()=>onRepair(token)}
              aria-busy={busy}
            >
              {busy ? <span className="repairSpinner" aria-hidden="true" /> : <span className="repairPulse" aria-hidden="true" />}
              <span>{busy ? "REPAIRING…" : "RUN SAFE REPAIR NOW"}</span>
            </button>
            <div className="repairTimestamp">
              <span>LAST REPAIR RUN</span>
              <strong>{ts(maintenance?.last_manual_repair?.completed_at_utc, "Never")}</strong>
              <small>
                {maintenance?.last_manual_repair
                  ? `${text(maintenance.last_manual_repair.outcome, "NO ACTION")} · ${num(maintenance.last_manual_repair.duration_ms, 0)} ms`
                  : "No manual repair has run in this worker session."}
              </small>
            </div>
          </div>
          <div className="repairTelemetry">
            <div><span>Agent mode</span><strong>{controls.master_enabled===false ? "OFF" : text(maintenance?.last_result?.maintenance_mode, maintenance?.healthy_baseline_established ? "MAINTAINING" : "BASELINE PENDING")}</strong></div>
            <div><span>Idle guard</span><strong>{num(maintenance?.idle_timeout_seconds)}s</strong></div>
            <div><span>Repair deadline</span><strong>{num(maintenance?.repair_timeout_seconds)}s</strong></div>
            <div><span>Last action</span><strong>{text(maintenance?.last_manual_repair?.action, "none")}</strong></div>
          </div>
          {busy ? (
            <div className="repairProgress" role="status">
              <span className="repairProgressBar"><i /></span>
              <div><strong>Maintenance repair in progress</strong><small>Diagnosing first causal clog → checking authority → applying smallest safe repair. Idle progress is bounded; the run is ended instead of hanging.</small></div>
            </div>
          ) : null}
          <p className="repairNote">Master OFF makes the Maintenance Agent inert. Automatic repair remains separately controllable. Manual repair never enables LIVE or forces a trade.</p>
        </div>
        {error ? <div className="errorBox">{error}</div> : null}
      </Section>
    </div>
  );
}

function AppPage({ active, data, nowMs, onToggle, onRepair, busy, controlError }) {
  const { floor, ingress, strategy, discovery, operator, maintenance } = data;
  if (active === "markets") return <Markets discovery={discovery} ingress={ingress} nowMs={nowMs} />;
  if (active === "pipeline") return <Pipeline strategy={strategy} discovery={discovery} ingress={ingress} maintenance={maintenance} floor={floor} operator={operator} />;
  if (active === "trading") return <TradingFloor strategy={strategy} />;
  if (active === "positions") return <Positions floor={floor} nowMs={nowMs} />;
  if (active === "blotter") return <Blotter operator={operator} />;
  if (active === "maintenance") return <Maintenance maintenance={maintenance} />;
  if (active === "settings") return <Settings ingress={ingress} strategy={strategy} discovery={discovery} floor={floor} maintenance={maintenance} onToggle={onToggle} onRepair={onRepair} busy={busy} error={controlError} />;
  return <CommandCenter floor={floor} ingress={ingress} strategy={strategy} discovery={discovery} operator={operator} maintenance={maintenance} nowMs={nowMs} />;
}

export default function DashboardPage() {
  const [active, setActive] = useState("command");
  const [data, setData] = useState({ floor:null, ingress:null, strategy:null, operator:null, discovery:null, maintenance:null });
  const [errors, setErrors] = useState([]);
  const [nowMs, setNowMs] = useState(()=>Date.now());
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const [maintenanceError, setMaintenanceError] = useState("");

  useEffect(()=>{
    const timer=setInterval(()=>setNowMs(Date.now()),1000);
    return()=>clearInterval(timer);
  },[]);

  useEffect(()=>{
    let mounted=true;
    const load=async()=>{
      const results=await Promise.allSettled([
        getJson(floorPath), getJson(ingressPath), getJson(strategyPath),
        getJson(operatorPath), getJson(discoveryPath), getJson(maintenancePath),
      ]);
      if(!mounted)return;
      const keys=["floor","ingress","strategy","operator","discovery","maintenance"];
      const next={}; const nextErrors=[];
      results.forEach((r,i)=>{
        if(r.status==="fulfilled") next[keys[i]]=r.value;
        else nextErrors.push(keys[i]);
      });
      setData((current)=>({...current,...next}));
      setErrors(nextErrors);
    };
    load();
    const timer=setInterval(load,5000);
    return()=>{mounted=false;clearInterval(timer);};
  },[]);

  const onToggle=async(key,enabled,token)=>{
    setMaintenanceBusy(true); setMaintenanceError("");
    try{
      const result=await postJson(`${maintenancePath}/controls/${encodeURIComponent(key)}`,{enabled},token);
      setData((current)=>({...current,maintenance:{...(current.maintenance||{}),controls:result.controls}}));
    }catch(err){setMaintenanceError(err instanceof Error?err.message:"Maintenance control update failed.");}
    finally{setMaintenanceBusy(false);}
  };
  const onRepair=async(token)=>{
    setMaintenanceBusy(true); setMaintenanceError("");
    try{
      const serverDeadline = Number(data.maintenance?.repair_timeout_seconds || 25);
      const result=await postJson(
        `${maintenancePath}/repair`,
        undefined,
        token,
        Math.max(8000, (serverDeadline + 5) * 1000),
      );
      setData((current)=>({
        ...current,
        maintenance:{
          ...(current.maintenance||{}),
          last_result:result.result,
          last_manual_repair:result.operation || current.maintenance?.last_manual_repair || null,
        },
      }));
    }catch(err){setMaintenanceError(err instanceof Error?err.message:"Maintenance repair failed.");}
    finally{setMaintenanceBusy(false);}
  };

  const title = NAV.find(([id])=>id===active)?.[1] || "Command Center";
  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brand"><img src="/vnext/aether-mark.png" alt="AETHER" /><div><strong>AETHER</strong><span>Autonomous Market Operations</span></div></div>
        <nav>
          {NAV.map(([id,label,sub])=>(
            <button type="button" className={active===id?"navItem active":"navItem"} onClick={()=>setActive(id)} key={id}>
              <span>{label}</span><small>{sub}</small>
            </button>
          ))}
        </nav>
        <div className="sidebarFoot"><Badge value="GREEN">PAPER ACTIVE</Badge><Badge value="BLOCKED">LIVE BLOCKED</Badge></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><span className="kicker">AETHER / SANDBOX</span><h1>{title}</h1></div>
          <div className="topbarMeta">
            <span>App restarted {ts(data.floor?.runtime_started_at_utc,"waiting")}</span>
            <span>Data refreshed {ts(data.floor?.as_of_utc,"waiting")}</span>
          </div>
        </header>

        <RuntimeStrip floor={data.floor} ingress={data.ingress} strategy={data.strategy} discovery={data.discovery} maintenance={data.maintenance} />

        {errors.length ? <div className="errorBox"><strong>Telemetry degraded:</strong> {errors.join(", ")} endpoint(s) unavailable. Existing UI state is preserved; no placeholder trade state is invented.</div> : null}

        <AppPage active={active} data={data} nowMs={nowMs} onToggle={onToggle} onRepair={onRepair} busy={maintenanceBusy} controlError={maintenanceError} />
      </section>
    </main>
  );
}
