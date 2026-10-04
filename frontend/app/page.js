"use client";

import { useEffect, useMemo, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";
const floorPath = process.env.NEXT_PUBLIC_AETHER_FLOOR_PATH || "/api/v1/vnext/floor";
const ingressPath = "/api/v1/vnext/ingress-runtime";
const strategyPath = "/api/v1/vnext/strategy-runtime";
const operatorPath = "/api/v1/vnext/operator";
const discoveryPath = "/api/v1/vnext/discovery-runtime";
const maintenancePath = "/api/v1/vnext/maintenance";
const tapePath = "/api/v1/vnext/tape";

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

function isObservedNumber(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function num(value, digits = 0, fallback = "NOT OBSERVED") {
  if (!isObservedNumber(value)) return fallback;
  const parsed = Number(value);
  return parsed.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function money(value, fallback = "NOT OBSERVED") {
  if (!isObservedNumber(value)) return fallback;
  const parsed = Number(value);
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
  if (!Number.isFinite(stamp)) return "NOT OBSERVED";
  const seconds = Math.max(0, Math.floor((nowMs - stamp) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function duration(value, nowMs) {
  const stamp = Date.parse(value || "");
  if (!Number.isFinite(stamp)) return "NOT OBSERVED";
  const seconds = Math.max(0, Math.floor((nowMs - stamp) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

function tone(value) {
  const v = String(value || "").toUpperCase();
  if (["CLEAR","RUNNING","ONLINE","OPEN","READY","GREEN","ACTIVE","FULL","HIGH"].includes(v)) return "good";
  if (["FAULT","BLOCKED","HALT","REJECT","ERROR","OFFLINE","STALLED","UNSAFE","CONTESTED"].includes(v)) return "bad";
  if (["DEGRADED","SINGLE_SOURCE","CREDENTIAL_REQUIRED","WAIT","WATCH","FIRE","STARTING","SYNCING","BUSY","CATCHING_UP","BASELINE_PENDING","RECOVERY","RECOVERY_BEFORE_BASELINE"].includes(v)) return "warn";
  return "neutral";
}

function Badge({ children, value }) {
  return <span className={`badge ${tone(value ?? children)}`}>{children}</span>;
}

const NAV = [
  ["command", "Command Center", "Overview"],
  ["markets", "Markets", "Provider universe"],
  ["tape", "Market Fabric", "Executable + intelligence truth"],
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

function supervisorState(supervisor, nowMs) {
  if (!supervisor) return "NOT OBSERVED";
  if (supervisor.enabled === false) return "OFF";
  if (!isObservedNumber(supervisor.cycle_count) || typeof supervisor.running !== "boolean") return "NOT OBSERVED";
  const cycles = Number(supervisor.cycle_count);
  if (supervisor.running !== true) return cycles > 0 ? "BLOCKED" : "WAIT";
  const started = Date.parse(supervisor.last_cycle_started_at_utc || "");
  const finished = Date.parse(supervisor.last_cycle_finished_at_utc || "");
  const progressHeartbeat = Date.parse(supervisor?.progress?.last_progress_at_utc || "");
  const intervalMs = isObservedNumber(supervisor.interval_seconds)
    ? Number(supervisor.interval_seconds) * 1000
    : 15000;
  const idleStaleAfterMs = Math.max(90000, intervalMs * 4);
  const progressState = String(supervisor?.progress?.cycle_state || "").toLowerCase();
  const cycleBusy = progressState === "running"
    || (Number.isFinite(started) && (!Number.isFinite(finished) || started > finished));
  if (cycleBusy) {
    const busyHeartbeat = Number.isFinite(progressHeartbeat) ? progressHeartbeat : started;
    const busyStaleAfterMs = Math.max(
      90000,
      isObservedNumber(supervisor?.progress?.provider_deadline_seconds)
        ? Number(supervisor.progress.provider_deadline_seconds) * 1500
        : 90000,
    );
    if (Number.isFinite(busyHeartbeat) && nowMs - busyHeartbeat > busyStaleAfterMs) return "STALLED";
    return "BUSY";
  }
  // Match backend health semantics exactly: a previous-cycle error is not a
  // current FAULT while a fresh recovery cycle is actively making progress.
  if (supervisor.last_error) return "FAULT";
  if (cycles === 0) return "STARTING";
  const heartbeat = Number.isFinite(finished)
    ? finished
    : Number.isFinite(progressHeartbeat)
      ? progressHeartbeat
      : started;
  if (Number.isFinite(heartbeat) && nowMs - heartbeat > idleStaleAfterMs) return "STALLED";
  return "ACTIVE";
}

function pipelineRuntimeState(ingress, discovery, tape, strategy, maintenance, nowMs) {
  const states = [
    supervisorState(ingress, nowMs),
    supervisorState(discovery, nowMs),
    supervisorState(tape?.runtime, nowMs),
    supervisorState(strategy, nowMs),
  ];
  if (states.includes("FAULT")) return "DEGRADED";
  if (states.includes("STALLED")) return "STALLED";
  if (states.includes("BLOCKED") || states.includes("OFF")) return "BLOCKED";
  if (states.some((state) => ["STARTING","BUSY","WAIT"].includes(state))) return "BUSY";
  if (states.every((state) => state === "ACTIVE")) {
    const maintenanceState = String(maintenance?.last_result?.status || "").toUpperCase();
    if (["FAULT","BLOCKED","DEGRADED","STALLED"].includes(maintenanceState)) return "DEGRADED";
    return "ACTIVE";
  }
  return "NOT OBSERVED";
}

function telemetryWatermark(data) {
  const stamps = [
    data.floor?.refresh_time_utc || data.floor?.as_of_utc,
    data.ingress?.last_cycle_finished_at_utc,
    data.strategy?.last_cycle_finished_at_utc,
    data.discovery?.last_cycle_finished_at_utc,
    data.tape?.runtime?.last_cycle_finished_at_utc || data.tape?.as_of_utc,
    data.maintenance?.last_result?.as_of_utc || data.maintenance?.as_of_utc,
  ].map((value) => Date.parse(value || "")).filter(Number.isFinite);
  if (stamps.length < 6) return null;
  return new Date(Math.min(...stamps)).toISOString();
}


function strategySnapshotId(strategy) {
  const finished = strategy?.last_result?.finished_at_utc || strategy?.last_cycle_finished_at_utc;
  const cycle = strategy?.cycle_count;
  if (!finished && !isObservedNumber(cycle)) return null;
  return `strategy-${cycle ?? "na"}-${finished || "open"}`;
}

function RuntimeStrip({ floor, ingress, strategy, discovery, tape, maintenance, nowMs }) {
  const ingressState = supervisorState(ingress, nowMs);
  const discoveryState = supervisorState(discovery, nowMs);
  const tapeState = supervisorState(tape?.runtime, nowMs);
  const strategyState = supervisorState(strategy, nowMs);
  const pipeline = pipelineRuntimeState(ingress, discovery, tape, strategy, maintenance, nowMs);
  return (
    <div className="runtimeStrip">
      <div><span>BUILD</span><b>{text(floor?.build?.source_revision?.slice(0, 8), "NOT OBSERVED")}</b></div>
      <div><span>SNAPSHOT</span><b>{text(floor?.snapshot_id || strategySnapshotId(strategy), "NOT OBSERVED")}</b></div>
      <div><span>FLOOR REFRESHED</span><b>{ts(floor?.refresh_time_utc || floor?.as_of_utc || strategy?.last_result?.finished_at_utc, "NOT OBSERVED")}</b></div>
      <div><span>INGRESS</span><Badge value={ingressState}>{ingressState}</Badge></div>
      <div><span>DISCOVERY</span><Badge value={discoveryState}>{discoveryState}</Badge></div>
      <div><span>TAPE</span><Badge value={tapeState}>{tapeState}</Badge></div>
      <div><span>STRATEGY</span><Badge value={strategyState}>{strategyState}</Badge></div>
      <div><span>PIPELINE</span><Badge value={pipeline}>{pipeline}</Badge></div>
    </div>
  );
}

function CommandCenter({ floor, ingress, strategy, discovery, tape, operator, maintenance, nowMs }) {
  const universe = Array.isArray(floor?.full_universe) ? floor.full_universe : [];
  const positionsObserved = Array.isArray(floor?.open_cockpits);
  const positions = positionsObserved ? floor.open_cockpits : [];
  const providers = providerRows(discovery);
  const catalog = observedSum(providers.map((r) => r.catalog_count));
  const eligible = observedSum(providers.map((r) => r.eligible_count));
  const focusRaw = discovery?.last_result?.focus_admitted_count;
  const focus = focusRaw === null || focusRaw === undefined ? null : Number(focusRaw);
  const pipe = strategy?.last_result?.pipeline || {};
  const strategyObserved = Boolean(strategy?.last_result && (strategy.last_result.assets || strategy.last_result.dynamic_assets));
  const strategyRows = combinedStrategyRows(strategy).slice(0, 12);
  const maintenanceState = maintenance?.last_result || {};
  const tapeSummary = tape?.summary || {};
  const tapeStates = tapeSummary.state_counts || {};
  const tapeFull = Number(tapeStates.FULL || 0);
  const tapeObserved = isObservedNumber(tapeSummary.asset_count) ? Number(tapeSummary.asset_count) : null;
  const tapeRuntimeState = supervisorState(tape?.runtime, nowMs);
  const bank = operator?.bank || {};
  const eventsObserved = Array.isArray(operator?.activity);
  const events = eventsObserved ? operator.activity : [];
  return (
    <div className="pageGrid">
      <div className="hero">
        <div>
          <span className="kicker">AETHER SANDBOX OPERATIONS</span>
          <h2>Autonomous market operations console</h2>
          <p>Provider-wide discovery, pipeline state, strategy activity, risk and self-healing in one command surface.</p>
        </div>
        <div className="heroModes">
          <Badge value={floor?.mode?.paper_only === true ? "GREEN" : floor?.mode?.paper_only === false ? "UNSAFE" : "NOT OBSERVED"}>
            {floor?.mode?.paper_only === true ? "PAPER ACTIVE" : floor?.mode?.paper_only === false ? "PAPER UNSAFE" : "PAPER NOT OBSERVED"}
          </Badge>
          <Badge value={floor?.mode?.live_blocked === true ? "BLOCKED" : floor?.mode?.live_blocked === false ? "UNSAFE" : "NOT OBSERVED"}>
            {floor?.mode?.live_blocked === true ? "LIVE BLOCKED" : floor?.mode?.live_blocked === false ? "LIVE NOT BLOCKED" : "LIVE NOT OBSERVED"}
          </Badge>
          <Badge value={maintenanceState.status || "SYNCING"}>{text(maintenanceState.status, "SYNCING")}</Badge>
        </div>
      </div>

      <div className="metricGrid">
        <Metric label="Catalog instruments" value={catalog === null ? "NOT OBSERVED" : num(catalog)} sub="Discovery-visible; not execution permission" />
        <Metric label="Focus admitted" value={focus === null ? "NOT OBSERVED" : num(focus)} sub={eligible === null ? "eligibility NOT OBSERVED" : `${num(eligible)} eligible · priority only`} />
        <Metric label="Evaluated this cycle" value={pipe.strategy_evaluated === undefined ? "NOT OBSERVED" : num(pipe.strategy_evaluated)} sub={pipe.market_ready === undefined ? "market readiness NOT OBSERVED" : `${num(pipe.market_ready)} market ready`} />
        <Metric label="Open positions" value={positionsObserved ? num(positions.length) : "NOT OBSERVED"} sub="PAPER positions" />
        <Metric label="Book cash" value={money(bank.book_cash_usd, "NOT OBSERVED")} sub={bank.cash_reserved_usd === null || bank.cash_reserved_usd === undefined ? "reserved NOT OBSERVED" : `${money(bank.cash_reserved_usd)} reserved`} />
        <Metric label="Maintenance" value={text(maintenanceState.status, "SYNCING")} sub={text(maintenanceState.primary_reason, "establishing baseline")} state={maintenanceState.status} />
        <Metric label="Consensus Tape" value={tapeObserved === null ? "NOT OBSERVED" : `${num(tapeFull)}/${num(tapeObserved)} FULL`} sub={`runtime ${tapeRuntimeState}`} state={tapeFull > 0 ? "FULL" : tapeObserved ? "DEGRADED" : tapeRuntimeState} />
      </div>

      <Section eyebrow="UNIVERSE CONTRACT" title="Catalog → commissioned → active work" className="wide">
        <div className="universeContract">
          <div><span>Provider catalog</span><strong>{catalog === null ? "NOT OBSERVED" : num(catalog)}</strong><small>Discovery-visible across providers; not execution permission.</small></div>
          <div><span>Catalog eligible</span><strong>{eligible === null ? "NOT OBSERVED" : num(eligible)}</strong><small>Provider discovery eligibility only.</small></div>
          <div><span>Kraken commissioned</span><strong>{pipe.dynamic_kraken_available === undefined ? "NOT OBSERVED" : num(pipe.dynamic_kraken_available)}</strong><small>Runtime-bound products with the current commissioned strategy route.</small></div>
          <div><span>Current roaming workset</span><strong>{pipe.roaming_batch === undefined ? "NOT OBSERVED" : num(pipe.roaming_batch)}</strong><small>All commissioned products remain owned; worker concurrency schedules I/O only.</small></div>
          <div><span>Market ready this cycle</span><strong>{pipe.market_ready === undefined ? "NOT OBSERVED" : num(pipe.market_ready)}</strong><small>Executable market evidence observed this cycle.</small></div>
          <div><span>Tape-governed seeds</span><strong>{pipe.tape_seed_required === undefined ? "NOT OBSERVED" : `${num(pipe.tape_seed_ready)}/${num(pipe.tape_seed_required)}`}</strong><small>FULL independent consensus required for covered seed strategy market truth.</small></div>
          <div><span>Floor runtime registry</span><strong>{Array.isArray(floor?.full_universe) ? num(universe.length) : "NOT OBSERVED"}</strong><small>Seed + commissioned dynamic products; not the provider catalog.</small></div>
        </div>
        <p className="universeTruth">Catalog-visible ≠ commissioned ≠ market-ready ≠ setup-qualified. AETHER keeps these populations separate so a large provider catalog cannot be mistaken for trade permission.</p>
      </Section>

      <Section eyebrow="PIPELINE" title="Operational flow" action={<span>{text(maintenanceState.first_causal_edge, maintenance ? "No causal clog" : "NOT OBSERVED")}</span>} className="wide">
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
          )) : <div className="empty">{strategyObserved ? "No strategy activity reported this cycle." : "Strategy activity NOT OBSERVED."}</div>}
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
          {!eventsObserved ? <div className="empty">Firm activity ledger NOT OBSERVED.</div> : !events.length ? <div className="empty">No recorded Firm events yet.</div> : null}
        </div>
      </Section>

      <Section eyebrow="OPEN RISK" title="Active positions" className="wide">
        {!positionsObserved
          ? <div className="empty">Position book NOT OBSERVED.</div>
          : positions.length
            ? <div className="positionGrid">{positions.map((row) => <PositionCard row={row} nowMs={nowMs} key={row.position_key} />)}</div>
            : <div className="empty">No open PAPER positions.</div>}
      </Section>
    </div>
  );
}

function Markets({ discovery, ingress, tape, nowMs }) {
  const [filter, setFilter] = useState("");
  const rows = providerRows(discovery);
  const quotes = ingress?.last_result?.quotes || [];
  const quoteMap = Object.fromEntries(quotes.map((q) => [String(q.symbol || "").toUpperCase(), q]));
  return (
    <div className="pageGrid">
      <div className="pageIntro">
        <div><span className="kicker">MARKET INTELLIGENCE</span><h2>Provider universe</h2><p>Catalog visibility is execution-provider discovery truth. Independent price authority lives in AETHER Tape; provider availability and Tape-source availability are separate failure domains.</p></div>
        <input className="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter instruments…" />
      </div>
      <Section eyebrow="MARKET DATA PLANE" title="Tape independence" className="wide">
        <div className="providerStats">
          <Metric label="Tape runtime" value={supervisorState(tape?.runtime, nowMs)} state={supervisorState(tape?.runtime, nowMs)} />
          <Metric label="Observed Tape assets" value={num(tape?.summary?.asset_count)} />
          <Metric label="FULL consensus" value={num(tape?.summary?.state_counts?.FULL, 0, "0")} state={Number(tape?.summary?.state_counts?.FULL || 0) ? "FULL" : "NOT OBSERVED"} />
          <Metric label="Independent sources" value={num((tape?.source_registry || []).filter((row) => row?.independent === true).length)} />
        </div>
        <p className="repairNote">Execution providers below can fail independently. A broker catalog being online does not make its quote the official Tape mark.</p>
      </Section>
      {rows.map((row) => {
        const items = (row.top100 || []).filter((item) => !filter || String(item.symbol || "").toLowerCase().includes(filter.toLowerCase()));
        return (
          <Section
            eyebrow={row.catalog_mode === "provider_native" ? "NATIVE CATALOG" : "REFERENCE CATALOG"}
            title={row.provider}
            action={<Badge value={row.status === "online" ? "ONLINE" : row.status === "NOT OBSERVED" ? "NOT OBSERVED" : "FAULT"}>{row.status === "online" ? (row.catalog_mode === "provider_native" ? "NATIVE CATALOG ONLINE" : "REFERENCE CATALOG ONLINE") : String(row.status || "NOT OBSERVED").toUpperCase()}</Badge>}
            className="wide"
            key={row.provider}
          >
            <div className="providerStats">
              <Metric label="Catalog" value={num(row.catalog_count)} />
              <Metric label="Eligible" value={num(row.eligible_count)} />
              <Metric label="Priority pool" value={num(row.focus_count)} />
              <Metric label="Data mode" value={text(row.catalog_mode, "NOT OBSERVED").replaceAll("_", " ")} />
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
                    {isObservedNumber(item.change_pct)
                      ? <span className={Number(item.change_pct) < 0 ? "loss" : Number(item.change_pct) > 0 ? "gain" : ""}>{Number(item.change_pct) >= 0 ? "+" : ""}{num(item.change_pct, 2)}%</span>
                      : <span>NOT OBSERVED</span>}
                    <span>{money(item.price)}</span>
                    <span>{age(q?.reference_ts_utc, nowMs)}</span>
                    <Badge value="PRIORITY">CATALOG PRIORITY</Badge>
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

function Tape({ tape, ingress, nowMs }) {
  const assets = Array.isArray(tape?.assets) ? tape.assets : [];
  const sources = Array.isArray(tape?.source_registry) ? tape.source_registry : [];
  const quotes = Array.isArray(ingress?.last_result?.quotes) ? ingress.last_result.quotes : [];
  const quoteByAsset = Object.fromEntries(
    quotes.map((row) => [String(row.asset_id || "").toLowerCase(), row])
  );
  const evidenceByAsset = Object.fromEntries(
    assets.map((row) => [String(row.asset_id || "").toLowerCase(), row])
  );
  const instrumentIds = [...new Set([
    ...Object.keys(quoteByAsset),
    ...Object.keys(evidenceByAsset),
  ])].sort();
  const summary = tape?.summary || {};
  const states = summary.state_counts || {};
  const runtime = tape?.runtime || {};
  const runtimeState = supervisorState(runtime, nowMs);
  const runtimeProgress = runtime?.progress || {};
  return (
    <div className="pageGrid">
      <div className="pageIntro">
        <div>
          <span className="kicker">AETHER MARKET FABRIC</span>
          <h2>Dual-domain Market Tape</h2>
          <p>Executable truth is the authorized execution-route book. Market Intelligence is independent witness evidence and derived analytics. Intelligence may corroborate or block action; it never overwrites executable bid/ask.</p>
        </div>
        <div className="heroModes">
          <Badge value={runtimeState}>{runtimeState}</Badge>
          <Badge value={Number(states.FULL || 0) > 0 ? "FULL" : assets.length ? "DEGRADED" : "NOT OBSERVED"}>
            {Number(states.FULL || 0) > 0 ? "EVIDENCE FULL" : assets.length ? "EVIDENCE PARTIAL" : "EVIDENCE NOT OBSERVED"}
          </Badge>
        </div>
      </div>

      <Section eyebrow="DUAL-DOMAIN TAPE" title="Executable truth + Market Intelligence" className="wide">
        <div className="marketTable">
          <div className="marketHead"><span>Instrument</span><span>Exec venue</span><span>Bid</span><span>Ask</span><span>Exec age</span><span>Evidence</span><span>Witnesses</span></div>
          {instrumentIds.map((assetId) => {
            const quote = quoteByAsset[assetId];
            const evidence = evidenceByAsset[assetId];
            return (
              <div className="marketRow" key={assetId}>
                <strong>{assetId.toUpperCase()}</strong>
                <span>{text(quote?.venue || quote?.source_id, "NOT OBSERVED")}</span>
                <span>{num(quote?.bid, 6)}</span>
                <span>{num(quote?.ask, 6)}</span>
                <span>{age(quote?.reference_ts_utc, nowMs)}</span>
                <Badge value={evidence?.state}>{text(evidence?.state, "NOT OBSERVED")}</Badge>
                <span>{isObservedNumber(evidence?.source_count) ? num(evidence.source_count) : "NOT OBSERVED"}</span>
              </div>
            );
          })}
          {!instrumentIds.length ? <div className="empty">No executable or evidence observation has been observed. AETHER does not invent zeroes or carry stale prices forward.</div> : null}
        </div>
        <p className="repairNote">Current shadow telemetry still exposes the legacy evidence source count. Effective-independence quorum is a v3 Market Fabric contract and remains NOT OBSERVED until its runtime persistence path is bound; this screen does not fabricate it.</p>
      </Section>

      <Section eyebrow="EXECUTABLE TAPE" title="Authorized-route observations" className="wide">
        <div className="eventList">
          {quotes.slice(0, 80).map((row) => (
            <div className="eventRow" key={`${row.asset_id}:${row.reference_ts_utc || row.received_ts_utc}`}>
              <time>{age(row.reference_ts_utc, nowMs)}</time>
              <div>
                <strong>{text(row.asset_id).toUpperCase()} · {text(row.venue)} · {num(row.bid, 6)} / {num(row.ask, 6)}</strong>
                <span>{text(row.source_id)} · last {num(row.last, 6)} · executable-source observation</span>
              </div>
            </div>
          ))}
          {!quotes.length ? <div className="empty">Executable-route observations NOT OBSERVED.</div> : null}
        </div>
      </Section>

      <Section eyebrow="MARKET INTELLIGENCE" title="Independent witness evidence" className="wide">
        <div className="providerStats">
          <Metric label="Observed assets" value={num(summary.asset_count)} />
          <Metric label="Full evidence" value={num(states.FULL, 0, "0")} state={Number(states.FULL || 0) ? "FULL" : "NOT OBSERVED"} />
          <Metric label="Degraded" value={num(states.DEGRADED, 0, "0")} state={Number(states.DEGRADED || 0) ? "DEGRADED" : "CLEAR"} />
          <Metric label="Contested" value={num(states.CONTESTED, 0, "0")} state={Number(states.CONTESTED || 0) ? "CONTESTED" : "CLEAR"} />
          <Metric label="Accepted witnesses" value={num(summary.accepted_source_count)} />
          <Metric label="Rejected witnesses" value={num(summary.rejected_source_count)} />
          <Metric label="Evidence cycles" value={num(runtime?.cycle_count)} sub={text(runtimeProgress.phase, "idle").replaceAll("_", " ")} />
          <Metric label="Heartbeat" value={age(runtimeProgress.last_progress_at_utc || runtime?.last_cycle_finished_at_utc, nowMs)} />
        </div>
      </Section>

      <Section eyebrow="SOURCE REGISTRY" title="Witness and transport dependencies" className="wide">
        <div className="marketTable">
          <div className="marketHead"><span>Source</span><span>Provider</span><span>Market</span><span>Implemented</span><span>Configured</span><span>Independent</span><span>State</span></div>
          {sources.map((row) => (
            <div className="marketRow" key={row.source_id}>
              <strong>{text(row.source_id)}</strong>
              <span>{text(row.provider)}</span>
              <span>{text(row.market).replaceAll("_", " ")}</span>
              <span>{row.implemented === true ? "YES" : row.implemented === false ? "NO" : "NOT OBSERVED"}</span>
              <span>{row.configured === true ? "YES" : row.configured === false ? "NO" : "NOT OBSERVED"}</span>
              <span>{row.independent === true ? "YES" : row.independent === false ? "NO" : "NOT OBSERVED"}</span>
              <Badge value={row.state}>{text(row.state, "NOT OBSERVED")}</Badge>
            </div>
          ))}
          {!sources.length ? <div className="empty">Market Fabric source registry NOT OBSERVED.</div> : null}
        </div>
      </Section>

      <Section eyebrow="PROVENANCE" title="Latest witness observations" className="wide">
        <div className="eventList">
          {assets.flatMap((asset) => (asset.sources || []).map((row) => ({ ...row, asset_id: asset.asset_id }))).slice(0, 60).map((row) => (
            <div className="eventRow" key={row.observation_id}>
              <time>{age(row.received_ts, nowMs)}</time>
              <div>
                <strong>{text(row.asset_id)} · {text(row.source_id)} · {num(row.mark, 6)}</strong>
                <span>{text(row.quality)} · {text(row.source_symbol)} · {text(row.source_ref)}</span>
              </div>
            </div>
          ))}
          {!assets.some((asset) => Array.isArray(asset.sources) && asset.sources.length) ? <div className="empty">Witness observations NOT OBSERVED.</div> : null}
        </div>
      </Section>
    </div>
  );
}

function floorQueueCount(floor, seat, state) {
  const row = (floor?.seat_queues || []).find((item) => item.seat === seat && item.state === state);
  return row && isObservedNumber(row.count) ? Number(row.count) : null;
}

const PIPELINE_TRUE_PREDICATES = {
  CATALOG: "eligible provider row → FOCUS_ADMITTED; provider rank is priority telemetry, not execution permission",
  FOCUS_ADMITTED: "projection.product != null && runtime_playbook_for_product(...) succeeds",
  PRODUCT_BOUND: "full commissioned compatible universe ordered OPEN/attention first; worker concurrency affects scheduling only and assets_dropped=0",
  ROAMING_SCAN: "Tape-governed assets require FULL AETHER consensus; otherwise canonical decision-time ingress observation must be valid, with binding/lifecycle gates still enforced",
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
    gate: "Full-universe work scheduler",
    plain: "Every commissioned compatible product remains in the work set. Open positions and attention-ranked assets move first, while bounded worker concurrency controls simultaneous history I/O without dropping eligibility.",
    dev: "prototype_strategy_supervisor._ordered_dynamic_strategy_work(...); configured_dynamic_strategy_scan_batch_size() controls workers only and _dynamic_flow_telemetry() proves assets_dropped=0.",
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

function Pipeline({ strategy, discovery, ingress, tape, maintenance, floor, operator, nowMs }) {
  const pipe = strategy?.last_result?.pipeline || {};
  const registry = strategy?.last_result?.dynamic_product_registry || {};
  const roam = strategy?.last_result?.dynamic_roam || {};
  const queue = (seat, state) => floorQueueCount(floor, seat, state);
  const counts = {
    CATALOG: observedSum(providerRows(discovery).map((row) => row.catalog_count)),
    FOCUS_ADMITTED: isObservedNumber(discovery?.last_result?.focus_admitted_count) ? Number(discovery.last_result.focus_admitted_count) : null,
    PRODUCT_BOUND: isObservedNumber(registry.persisted) ? Number(registry.persisted) : null,
    ROAMING_SCAN: isObservedNumber(pipe.roaming_batch) ? Number(pipe.roaming_batch) : null,
    MARKET_READY: isObservedNumber(pipe.market_ready) ? Number(pipe.market_ready) : null,
    HISTORY_READY: isObservedNumber(pipe.history_ready) ? Number(pipe.history_ready) : null,
    STRATEGY_EVALUATED: isObservedNumber(pipe.strategy_evaluated) ? Number(pipe.strategy_evaluated) : null,
    WATCH: queue("Scout", "WATCH") ?? (isObservedNumber(pipe.watch) ? Number(pipe.watch) : null),
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
  const eligible = observedSum(providerRows(discovery).map((row) => row.eligible_count));
  const dynamicAssetsObserved = strategy?.last_result?.dynamic_assets && typeof strategy.last_result.dynamic_assets === "object";
  const dynamicRows = dynamicAssetsObserved ? Object.values(strategy.last_result.dynamic_assets) : [];
  const ingressRows = ingress?.last_result?.asset_results || [];
  const queueRows = floor?.seat_queues || [];

  const gateTelemetry = (stage) => {
    if (stage === "CATALOG") {
      const complete = [catalog, eligible, counts.FOCUS_ADMITTED].every(isObservedNumber);
      return reconcileGate({
        input: catalog,
        pass: counts.FOCUS_ADMITTED,
        wait: complete ? Math.max(0, eligible - counts.FOCUS_ADMITTED) : null,
        reject: complete ? Math.max(0, catalog - eligible) : null,
        exact: complete && catalog >= eligible && eligible >= counts.FOCUS_ADMITTED,
        reasons: reasonHistogram(providerRows(discovery).filter((row) => row.status !== "online"), () => true),
      });
    }
    if (stage === "ROAMING_SCAN") {
      return reconcileGate({
        input: counts.ROAMING_SCAN,
        pass: counts.MARKET_READY,
        wait: isObservedNumber(pipe.market_not_ready) ? Number(pipe.market_not_ready) : null,
        reject: 0,
        exact: isObservedNumber(pipe.market_not_ready),
        reasons: reasonHistogram(dynamicRows, (row) => row?.stage === "MARKET_NOT_READY").concat(
          reasonHistogram(ingressRows, (row) => row?.executable === false)
        ).slice(0, 6),
      });
    }
    if (stage === "MARKET_READY") {
      return reconcileGate({
        input: counts.MARKET_READY,
        pass: counts.HISTORY_READY,
        wait: isObservedNumber(pipe.history_not_ready) ? Number(pipe.history_not_ready) : null,
        reject: 0,
        exact: isObservedNumber(pipe.history_not_ready),
        reasons: reasonHistogram(dynamicRows, (row) => row?.stage === "HISTORY_NOT_READY"),
      });
    }
    if (stage === "HISTORY_READY") {
      return reconcileGate({
        input: counts.HISTORY_READY,
        pass: counts.STRATEGY_EVALUATED,
        wait: 0,
        reject: 0,
        fault: isObservedNumber(pipe.evaluation_error) ? Number(pipe.evaluation_error) : null,
        exact: isObservedNumber(pipe.evaluation_error),
        reasons: reasonHistogram(dynamicRows, (row) => ["EVALUATION_ERROR", "PIPELINE_ERROR"].includes(row?.stage)),
      });
    }
    if (stage === "STRATEGY_EVALUATED") {
      const qualifiedObserved = isObservedNumber(pipe.watch) && isObservedNumber(pipe.fire_or_beyond);
      const qualified = qualifiedObserved ? Number(pipe.watch) + Number(pipe.fire_or_beyond) : null;
      const decisionRows = combinedStrategyRows(strategy);
      const noSetup = decisionRows.filter((row) => row?.stage === "NO_SETUP").length;
      const rowFaults = decisionRows.filter((row) => ["EVALUATION_ERROR", "PIPELINE_ERROR"].includes(row?.stage)).length;
      const declared = isObservedNumber(counts.STRATEGY_EVALUATED) ? Number(counts.STRATEGY_EVALUATED) : null;
      const evidenced = noSetup + (qualified || 0) + rowFaults;
      const input = declared === null ? (decisionRows.length ? evidenced : null) : Math.max(declared, evidenced);
      const complete = input !== null && qualified !== null && input === qualified + noSetup + rowFaults;
      return reconcileGate({
        input,
        pass: qualified,
        wait: complete ? 0 : null,
        reject: decisionRows.length || declared !== null ? noSetup : null,
        fault: rowFaults || (isObservedNumber(pipe.evaluation_error) ? Number(pipe.evaluation_error) : 0),
        exact: complete,
        reasons: reasonHistogram(decisionRows, (row) => row?.stage === "NO_SETUP"),
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
  const fullyReconciled = (row) => row.coverage === "FULL" && row.reconciled === true;
  const fullCoverage = Object.values(telemetryByStage).filter(fullyReconciled).length;
  const unexplainedTotal = Object.values(telemetryByStage).reduce(
    (sum, row) => sum + (fullyReconciled(row) ? Number(row.unexplained || 0) : 0),
    0
  );
  const m = maintenance?.last_result || {};
  const firstCausal = String(m.first_causal_edge || "").toUpperCase();
  const ingressProgress = ingress?.progress || {};
  const discoveryProgress = discovery?.progress || {};
  const strategyProgress = strategy?.progress || {};
  const tapeRuntime = tape?.runtime || {};
  const tapeProgress = tapeRuntime?.progress || {};
  const tapeStates = tape?.summary?.state_counts || {};
  const pipelineState = pipelineRuntimeState(ingress, discovery, tape, strategy, maintenance, nowMs);
  const progressRatio = (done, total) => (
    isObservedNumber(done) && isObservedNumber(total)
      ? `${num(done)}/${num(total)}`
      : "NOT OBSERVED"
  );

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

      <Section eyebrow="LIVE AGENT WORK" title="Current cycle progress" className="wide">
        <div className="constraintGrid">
          <div>
            <span>Ingress agent</span>
            <strong>{supervisorState(ingress, nowMs)} · {text(ingressProgress.phase, "NOT OBSERVED").replaceAll("_", " ")}</strong>
            <small>Quote batches {progressRatio(ingressProgress.completed_dynamic_chunk_count, ingressProgress.dynamic_chunk_count)} · assets persisted {progressRatio(ingressProgress.processed_asset_count, ingressProgress.eligible_asset_count)} · heartbeat {age(ingressProgress.last_progress_at_utc, nowMs)}</small>
          </div>
          <div>
            <span>Discovery agents</span>
            <strong>{supervisorState(discovery, nowMs)} · {text(discoveryProgress.cycle_state, "NOT OBSERVED").replaceAll("_", " ")}</strong>
            <small>Active providers {Array.isArray(discoveryProgress.active_providers) ? (discoveryProgress.active_providers.join(", ") || "none") : "NOT OBSERVED"} · current {text(discoveryProgress.current_provider, "none")} · heartbeat {age(discoveryProgress.last_progress_at_utc || discovery?.last_cycle_finished_at_utc, nowMs)}</small>
          </div>
          <div>
            <span>Tape agent</span>
            <strong>{supervisorState(tapeRuntime, nowMs)} · {text(tapeProgress.phase, "NOT OBSERVED").replaceAll("_", " ")}</strong>
            <small>FULL {num(tapeStates.FULL, 0, "0")} · degraded {num(tapeStates.DEGRADED, 0, "0")} · contested {num(tapeStates.CONTESTED, 0, "0")} · heartbeat {age(tapeProgress.last_progress_at_utc || tapeRuntime?.last_cycle_finished_at_utc, nowMs)}</small>
          </div>
          <div>
            <span>Strategy agents</span>
            <strong>{supervisorState(strategy, nowMs)} · {text(strategyProgress.phase, "NOT OBSERVED").replaceAll("_", " ")}</strong>
            <small>History workers {progressRatio(strategyProgress.history_fetch_completed, strategyProgress.history_fetch_total)} · cache hits {num(strategyProgress.history_cache_hits)} · candidates {num(strategyProgress.work_candidate_count)} · concurrency {num(strategyProgress.worker_concurrency)} · heartbeat {age(strategyProgress.last_progress_at_utc, nowMs)}</small>
          </div>
          <div>
            <span>Pipeline state</span>
            <strong><Badge value={pipelineState}>{pipelineState}</Badge></strong>
            <small>State is derived from observed supervisor movement and progress heartbeats, not task existence alone.</small>
          </div>
        </div>
      </Section>

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
          <div><span>Scan scheduler</span><strong>{isObservedNumber(roam.worker_concurrency) ? `${num(roam.worker_concurrency)} workers · range ${num(roam.configured_worker_concurrency_range?.minimum)}–${num(roam.configured_worker_concurrency_range?.maximum)}` : "NOT OBSERVED"}</strong><small>Worker capacity controls simultaneous history I/O only; it does not drop or gate eligible assets.</small></div>
          <div><span>Crypto regime input</span><strong>btc_kraken_daily still exists in warm-up</strong><small>This is a real code dependency to remove/generalize later, not a UI preference.</small></div>
          <div><span>Telemetry coverage</span><strong>{fullCoverage}/{PIPELINE_GATE_BLUEPRINT.length} gates fully reconcilable</strong><small>Unknown outcomes stay NOT OBSERVED; the UI does not invent zeroes.</small></div>
          <div className={unexplainedTotal ? "constraintFault" : ""}><span>Unexplained flow loss</span><strong>{num(unexplainedTotal)}</strong><small>{unexplainedTotal ? "Observed counts do not reconcile at one or more fully measured gates." : "No unexplained loss in fully measured gates."}</small></div>
        </div>
      </Section>

      <Section eyebrow="MARKET TRUTH DEPENDENCY" title="Tape → Gate 04" className="wide">
        <div className="constraintGrid">
          <div><span>Tape runtime</span><strong>{supervisorState(tapeRuntime, nowMs)}</strong><small>Independent from Kraken / NinjaTrader / tastyfx / IBKR execution-provider health.</small></div>
          <div><span>Seed quorum</span><strong>{pipe.tape_seed_required === undefined ? "NOT OBSERVED" : `${num(pipe.tape_seed_ready)}/${num(pipe.tape_seed_required)} ready`}</strong><small>Covered seed assets require FULL consensus before strategy market readiness.</small></div>
          <div><span>FULL composites</span><strong>{num(tapeStates.FULL, 0, "0")}</strong><small>3+ qualified agreeing independent feeds.</small></div>
          <div><span>Tape exceptions</span><strong>{num(Number(tapeStates.DEGRADED || 0) + Number(tapeStates.SINGLE_SOURCE || 0) + Number(tapeStates.CONTESTED || 0))}</strong><small>Degraded/single/contested remains visible but cannot silently become seed strategy authority.</small></div>
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
                        <strong>{observed ? num(value) : "NOT OBSERVED"}</strong>
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
                        {(() => {
                          const reveal = gate.coverage === "FULL" && gate.reconciled === true;
                          const show = (value) => reveal ? num(value) : "NOT OBSERVED";
                          return <>
                            <div><span>INPUT</span><strong>{show(gate.input)}</strong></div>
                            <div><span>PASS</span><strong>{show(gate.pass)}</strong></div>
                            <div><span>WAIT</span><strong>{show(gate.wait)}</strong></div>
                            <div><span>REJECT / NO SETUP</span><strong>{show(gate.reject)}</strong></div>
                            <div><span>FAULT</span><strong>{show(gate.fault)}</strong></div>
                            <div><span>UNEXPLAINED</span><strong className={reveal && Number(gate.unexplained || 0) > 0 ? "loss" : ""}>{show(gate.unexplained)}</strong></div>
                            <div><span>COVERAGE</span><strong>{gate.coverage}</strong></div>
                            <div><span>RECONCILED</span><strong>{gate.reconciled === null ? "NOT OBSERVED" : gate.reconciled ? "YES" : "NO"}</strong></div>
                          </>;
                        })()}
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

function Positions({ floor, nowMs, endpointHealth }) {
  const observed = endpointHealth?.floor === "live" && Array.isArray(floor?.open_cockpits);
  const rows = observed ? floor.open_cockpits : [];
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">OPEN RISK</span><h2>Positions</h2><p>Active PAPER positions remain managed regardless of discovery rank changes.</p></div></div>
      <Section eyebrow="POSITION BOOK" title={observed ? `${rows.length} open` : "NOT OBSERVED"} className="wide">
        {!observed ? <div className="empty">Position book NOT OBSERVED.</div> : rows.length ? <div className="positionGrid">{rows.map((row)=><PositionCard row={row} nowMs={nowMs} key={row.position_key} />)}</div> : <div className="empty">No open positions.</div>}
      </Section>
    </div>
  );
}

function Blotter({ operator, endpointHealth }) {
  const observed = endpointHealth?.operator === "live" && Array.isArray(operator?.blotter);
  const rows = observed ? operator.blotter : [];
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">EXECUTION HISTORY</span><h2>Blotter</h2><p>Completed PAPER round trips with cost and excursion telemetry.</p></div></div>
      <Section eyebrow="TRADE LEDGER" title={observed ? `${rows.length} completed` : "NOT OBSERVED"} className="wide">
        <div className="blotterTable">
          <div className="blotterHead"><span>Closed</span><span>Instrument</span><span>Side</span><span>Qty</span><span>Entry</span><span>Exit</span><span>Net</span><span>MFE</span><span>MAE</span><span>Reason</span></div>
          {rows.map((row)=>(
            <div className="blotterRow" key={row.trade_id}>
              <span>{ts(row.closed_at_utc,"—")}</span><strong>{text(row.asset_id).toUpperCase()}</strong><span>{text(row.side)}</span><span>{num(row.quantity,8)}</span><span>{num(row.avg_entry_price,8)}</span><span>{num(row.exit_price,8)}</span><span className={Number(row.net_pnl_usd)<0?"loss":Number(row.net_pnl_usd)>0?"gain":""}>{money(row.net_pnl_usd)}</span><span>{money(row.mfe_usd)}</span><span>{money(row.mae_usd)}</span><span>{text(row.exit_reason)}</span>
            </div>
          ))}
          {!observed ? <div className="empty">Trade ledger NOT OBSERVED. No completed-trade count is asserted while the operator endpoint is unavailable.</div> : !rows.length ? <div className="empty">No completed trades in this sandbox session.</div> : null}
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
          {!incidents.length ? <div className="empty">{maintenance?.incident_read_warning ? `Incident ledger NOT OBSERVED: ${maintenance.incident_read_warning}` : "No maintenance incidents recorded."}</div> : null}
        </div>
      </Section>
    </div>
  );
}

function Settings({ ingress, strategy, discovery, tape, floor, maintenance, onToggle, onRepair, busy, error }) {
  const [token, setToken] = useState("");
  const controls = maintenance?.controls || {};
  const labels = maintenance?.control_labels || {};
  const unlocked = token.trim().length > 0;
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">SYSTEM CONFIGURATION</span><h2>Settings</h2><p>Operational controls only. PAPER execution and LIVE hard block remain locked outside this UI.</p></div></div>
      <Section eyebrow="RUNTIME" title="Sandbox configuration" className="wide">
        <div className="settingsMetrics">
          <Metric label="Execution" value={floor?.mode?.paper_only === true ? "PAPER" : floor?.mode?.paper_only === false ? "UNSAFE" : "NOT OBSERVED"} state={floor?.mode?.paper_only === true ? "GREEN" : floor?.mode?.paper_only === false ? "UNSAFE" : "NOT OBSERVED"} sub="Canonical Floor mode" />
          <Metric label="Live" value={floor?.mode?.live_blocked === true ? "BLOCKED" : floor?.mode?.live_blocked === false ? "UNSAFE" : "NOT OBSERVED"} state={floor?.mode?.live_blocked === true ? "BLOCKED" : floor?.mode?.live_blocked === false ? "UNSAFE" : "NOT OBSERVED"} sub="Not configurable here" />
          <Metric label="Ingress cadence" value={`${num(ingress?.interval_seconds)}s`} />
          <Metric label="Strategy cadence" value={`${num(strategy?.interval_seconds)}s`} />
          <Metric label="Discovery" value={discovery?.running ? "RUNNING" : "WAIT"} state={discovery?.running ? "GREEN":"WARN"} />
          <Metric label="Tape" value={supervisorState(tape?.runtime, Date.now())} state={supervisorState(tape?.runtime, Date.now())} sub={isObservedNumber(tape?.runtime?.interval_seconds) ? `${num(tape.runtime.interval_seconds)}s cadence · quorum 3` : "cadence NOT OBSERVED"} />
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

function AppPage({ active, data, nowMs, onToggle, onRepair, busy, controlError, endpointHealth }) {
  const { floor, ingress, strategy, discovery, operator, maintenance, tape } = data;
  if (active === "markets") return <Markets discovery={discovery} ingress={ingress} tape={tape} nowMs={nowMs} />;
  if (active === "tape") return <Tape tape={tape} ingress={ingress} nowMs={nowMs} />;
  if (active === "pipeline") return <Pipeline strategy={strategy} discovery={discovery} ingress={ingress} tape={tape} maintenance={maintenance} floor={floor} operator={operator} nowMs={nowMs} />;
  if (active === "trading") return <TradingFloor strategy={strategy} />;
  if (active === "positions") return <Positions floor={floor} nowMs={nowMs} endpointHealth={endpointHealth} />;
  if (active === "blotter") return <Blotter operator={operator} endpointHealth={endpointHealth} />;
  if (active === "maintenance") return <Maintenance maintenance={maintenance} />;
  if (active === "settings") return <Settings ingress={ingress} strategy={strategy} discovery={discovery} tape={tape} floor={floor} maintenance={maintenance} onToggle={onToggle} onRepair={onRepair} busy={busy} error={controlError} />;
  return <CommandCenter floor={floor} ingress={ingress} strategy={strategy} discovery={discovery} tape={tape} operator={operator} maintenance={maintenance} nowMs={nowMs} />;
}

export default function DashboardPage() {
  const [active, setActive] = useState("command");
  const [data, setData] = useState({ floor:null, ingress:null, strategy:null, operator:null, discovery:null, maintenance:null, tape:null });
  const [errors, setErrors] = useState([]);
  const [endpointHealth, setEndpointHealth] = useState({});
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
        getJson(operatorPath), getJson(discoveryPath), getJson(maintenancePath), getJson(tapePath),
      ]);
      if(!mounted)return;
      const keys=["floor","ingress","strategy","operator","discovery","maintenance","tape"];
      const next={}; const nextErrors=[]; const health={};
      results.forEach((r,i)=>{
        if(r.status==="fulfilled") { next[keys[i]]=r.value; health[keys[i]]="live"; }
        else { nextErrors.push(keys[i]); health[keys[i]]="unavailable"; }
      });
      setData((current)=>({...current,...next}));
      setEndpointHealth((current)=>({...current,...health}));
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
  const watermark = telemetryWatermark(data);
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
        <div className="sidebarFoot">
          <Badge value={data.floor?.mode?.paper_only === true ? "GREEN" : data.floor?.mode?.paper_only === false ? "UNSAFE" : "NOT OBSERVED"}>
            {data.floor?.mode?.paper_only === true ? "PAPER ACTIVE" : data.floor?.mode?.paper_only === false ? "PAPER UNSAFE" : "PAPER NOT OBSERVED"}
          </Badge>
          <Badge value={data.floor?.mode?.live_blocked === true ? "BLOCKED" : data.floor?.mode?.live_blocked === false ? "UNSAFE" : "NOT OBSERVED"}>
            {data.floor?.mode?.live_blocked === true ? "LIVE BLOCKED" : data.floor?.mode?.live_blocked === false ? "LIVE NOT BLOCKED" : "LIVE NOT OBSERVED"}
          </Badge>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><span className="kicker">AETHER / SANDBOX</span><h1>{title}</h1></div>
          <div className="topbarMeta">
            <span>App restarted {ts(data.floor?.runtime_started_at_utc,"NOT OBSERVED")}</span>
            <span>Data refreshed · telemetry watermark {ts(watermark,"NOT OBSERVED")}</span>
          </div>
        </header>

        <RuntimeStrip floor={data.floor} ingress={data.ingress} strategy={data.strategy} discovery={data.discovery} tape={data.tape} maintenance={data.maintenance} nowMs={nowMs} />

        {errors.length ? <div className="errorBox"><strong>Telemetry degraded:</strong> {errors.join(", ")} endpoint(s) unavailable. Existing UI state is preserved; no placeholder trade state is invented.</div> : null}

        <AppPage active={active} data={data} nowMs={nowMs} onToggle={onToggle} onRepair={onRepair} busy={maintenanceBusy} controlError={maintenanceError} endpointHealth={endpointHealth} />
      </section>
    </main>
  );
}
