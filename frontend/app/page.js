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

async function postJson(path, body, operatorToken) {
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Operator-Token": operatorToken },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail || `${response.status} ${path}`);
  return payload;
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
  if (["DEGRADED","WAIT","WATCH","FIRE","STARTING","SYNCING"].includes(v)) return "warn";
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
  return PROVIDERS.map((provider) => ({
    provider,
    status: "waiting",
    reason: "waiting_for_discovery_cycle",
    catalog_count: 0,
    eligible_count: 0,
    focus_count: 0,
    top100: [],
    ...(providers[provider] || {}),
  }));
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
      <div><span>REFRESHED</span><b>{ts(floor?.as_of_utc)}</b></div>
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
  const catalog = providers.reduce((s, r) => s + Number(r.catalog_count || 0), 0);
  const eligible = providers.reduce((s, r) => s + Number(r.eligible_count || 0), 0);
  const focus = Number(discovery?.last_result?.focus_admitted_count || 0);
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
        <Metric label="Catalog instruments" value={num(catalog)} sub="Across connected provider lanes" />
        <Metric label="Focus admitted" value={num(focus)} sub={`${num(eligible)} eligible`} />
        <Metric label="Evaluated this cycle" value={num(pipe.strategy_evaluated || 0)} sub={`${num(pipe.market_ready || 0)} market ready`} />
        <Metric label="Open positions" value={num(positions.length)} sub="PAPER positions" />
        <Metric label="Book cash" value={money(bank.book_cash_usd, "$0.00")} sub={`${money(bank.cash_reserved_usd, "$0.00")} reserved`} />
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

function Pipeline({ strategy, discovery, maintenance, floor }) {
  const pipe = strategy?.last_result?.pipeline || {};
  const stages = [
    ["CATALOG", providerRows(discovery).reduce((s,r)=>s+Number(r.catalog_count||0),0)],
    ["FOCUS ADMITTED", Number(discovery?.last_result?.focus_admitted_count||0)],
    ["ROAMING", Number(pipe.roaming_batch||0)],
    ["MARKET READY", Number(pipe.market_ready||0)],
    ["HISTORY READY", Number(pipe.history_ready||0)],
    ["EVALUATED", Number(pipe.strategy_evaluated||0)],
    ["WATCH", Number(pipe.watch||0)],
    ["FIRE +", Number(pipe.fire_or_beyond||0)],
    ["OPEN", (floor?.open_cockpits||[]).length],
  ];
  const m = maintenance?.last_result || {};
  return (
    <div className="pageGrid">
      <div className="pageIntro"><div><span className="kicker">STATE MACHINE</span><h2>Pipeline control plane</h2><p>Every instrument should have an explainable current destination. Downstream zeros are not treated as independent faults.</p></div></div>
      <Section eyebrow="FLOW MAP" title="End-to-end progression" className="wide" action={<Badge value={m.status}>{text(m.status, "SYNCING")}</Badge>}>
        <div className="flowMap">
          {stages.map(([label,count], i) => <div className="flowNode" key={label}><span>{label}</span><strong>{num(count)}</strong>{i < stages.length-1 ? <i>→</i> : null}</div>)}
        </div>
      </Section>
      <Section eyebrow="FIRST CAUSAL CLOG" title={text(m.first_causal_edge, "No clog identified")}>
        <div className="diagnosis">
          <Badge value={m.status}>{text(m.status, "SYNCING")}</Badge>
          <dl>
            <div><dt>Owner</dt><dd>{text(m.owner)}</dd></div>
            <div><dt>Reason</dt><dd>{text(m.primary_reason)}</dd></div>
            <div><dt>Affected</dt><dd>{num(m.affected_count)}</dd></div>
            <div><dt>Confidence</dt><dd>{text(m.confidence)}</dd></div>
          </dl>
          <p>{text(m.observed, "Maintenance is establishing the healthy-system baseline.")}</p>
        </div>
      </Section>
      <Section eyebrow="RECOMMENDED ACTION" title="Maintenance guidance">
        <p className="longText">{text(m.recommended_action, "No corrective action recommended.")}</p>
        {(m.not_root_causes || []).length ? <div className="chipRow">{m.not_root_causes.map((x)=><span key={x}>{x} not root</span>)}</div> : null}
      </Section>
      <Section eyebrow="SEAT QUEUES" title="Current queue pressure" className="wide">
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
            <div><span>Agent</span><strong>{controls.master_enabled===false ? "OFF" : "READY"}</strong></div>
            <div><span>Auto repair</span><strong>{controls.auto_repair_enabled ? "ON" : "OFF"}</strong></div>
            <div><span>Level 1</span><strong>{controls.level1_safe_repair_enabled===false ? "OFF" : "ARMED"}</strong></div>
            <div><span>Last action</span><strong>{text(maintenance?.last_manual_repair?.action, "none")}</strong></div>
          </div>
          {busy ? (
            <div className="repairProgress" role="status">
              <span className="repairProgressBar"><i /></span>
              <div><strong>Maintenance repair in progress</strong><small>Diagnosing first causal clog → checking authority → applying smallest safe repair → verifying pipeline health.</small></div>
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
  if (active === "pipeline") return <Pipeline strategy={strategy} discovery={discovery} maintenance={maintenance} floor={floor} />;
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
      const result=await postJson(`${maintenancePath}/repair`,undefined,token);
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
