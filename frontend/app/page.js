"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";
const floorPath = process.env.NEXT_PUBLIC_AETHER_FLOOR_PATH || "/api/v1/vnext/floor";
const ingressPath = "/api/v1/vnext/ingress-runtime";
const strategyPath = "/api/v1/vnext/strategy-runtime";
const operatorPath = "/api/v1/vnext/operator";

async function getJson(path) {
  const response = await fetch(`${apiBase}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

function text(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function timestamp(value, fallback = "waiting") {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback;
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

function number(value, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function quotePrice(row) {
  if (!row) return null;
  for (const candidate of [row.mark, row.last]) {
    const parsed = Number(candidate);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  const bid = Number(row.bid);
  const ask = Number(row.ask);
  return Number.isFinite(bid) && Number.isFinite(ask) && bid > 0 && ask >= bid
    ? (bid + ask) / 2
    : null;
}

function ageLabel(value, nowMs) {
  if (!value) return "waiting";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "waiting";
  const seconds = Math.max(0, Math.floor((nowMs - parsed) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

function strategyCountdown(strategy, nowMs) {
  if (!strategy?.enabled || !strategy?.running || strategy?.last_error) return "waiting";
  const started = Date.parse(strategy?.last_cycle_started_at_utc || "");
  const finished = Date.parse(strategy?.last_cycle_finished_at_utc || "");
  if (Number.isFinite(started) && (!Number.isFinite(finished) || started > finished)) return "scanning…";
  if (!Number.isFinite(finished)) return "scanning…";
  const interval = Math.max(1, Number(strategy?.interval_seconds) || 60);
  const elapsed = Math.max(0, (nowMs - finished) / 1000);
  const remaining = Math.max(0, Math.ceil(interval - elapsed));
  return remaining > 0 ? `${remaining}s` : "scanning…";
}

function HeartbeatQuote({ assetId, row, direction, nowMs }) {
  const price = quotePrice(row);
  const arrow = direction > 0 ? "↑" : direction < 0 ? "↓" : "•";
  const moveClass = direction > 0 ? "up" : direction < 0 ? "down" : "";
  return (
    <div className="heartbeatQuote">
      <span>{text(row?.symbol, `${assetId.toUpperCase()}/USD`)}</span>
      <strong>
        {price === null ? "waiting" : `$${number(price, 2)}`}
        <em className={moveClass}>{arrow}</em>
      </strong>
      <small>quote age {ageLabel(row?.reference_ts_utc, nowMs)}</small>
    </div>
  );
}

function stateClass(state) {
  const value = String(state || "").toLowerCase();
  if (["open", "seeing", "ready"].includes(value)) return "state good";
  if (["fire", "size", "order", "watch"].includes(value)) return "state active";
  if (["reject", "halt"].includes(value)) return "state bad";
  return "state";
}

function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

function runtimeState(enabled, running, lastError) {
  if (lastError) return { label: "FAULT", className: "state bad" };
  if (enabled && running) return { label: "RUNNING", className: "state good" };
  if (enabled) return { label: "STARTING", className: "state active" };
  return { label: "OFF", className: "state" };
}

function StrategyDecision({ assetId, row }) {
  const stage = text(row?.stage, "WAITING");
  const reason = text(row?.reason, "waiting for first cycle");
  return (
    <article className="strategyDecision">
      <div className="strategyDecisionHead">
        <strong>{assetId.toUpperCase()}</strong>
        <span className={stateClass(stage)}>{stage}</span>
      </div>
      <dl className="mini">
        <div><dt>Reason</dt><dd>{reason}</dd></div>
        <div><dt>Trigger close</dt><dd>{timestamp(row?.trigger_close_utc, "waiting")}</dd></div>
        <div><dt>Vol percentile</dt><dd>{number(row?.volatility_percentile, 2)}</dd></div>
        <div><dt>Watch eligible</dt><dd>{row?.watch_eligible === true ? "YES" : row?.watch_eligible === false ? "NO" : "—"}</dd></div>
      </dl>
    </article>
  );
}

function UniverseCard({ station, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`station ${selected ? "selected" : ""}`}
      onClick={() => onSelect(station.asset_id)}
      aria-pressed={selected}
    >
      <div className="stationHead">
        <div>
          <strong>{text(station.symbol, station.asset_id?.toUpperCase())}</strong>
          <span>{text(station.product_type)}</span>
        </div>
        <span className={stateClass(station.dominant_state)}>
          {text(station.dominant_state, "NO")}
        </span>
      </div>
      <div className="stationMark">{number(station.mark, 8)}</div>
      <dl className="mini">
        <div><dt>Seat</dt><dd>{text(station.seat_owner)}</dd></div>
        <div><dt>Open</dt><dd>{text(station.open_position_count, "0")}</dd></div>
        <div><dt>First blocker</dt><dd>{text(station.first_blocker, "clear")}</dd></div>
      </dl>
    </button>
  );
}

function Queue({ queue }) {
  return (
    <article className="queueCard">
      <div className="queueHead">
        <div><span>{queue.seat}</span><strong>{queue.state}</strong></div>
        <b>{text(queue.count, queue.item_ids?.length || 0)}</b>
      </div>
      <div className="queueItems">
        {(queue.item_ids || []).slice(0, 5).map((id) => <span key={id}>{id}</span>)}
        {(queue.item_ids || []).length === 0 ? <em>Queue clear</em> : null}
      </div>
      <small>{text(queue.blocker_count, 0)} blocker(s)</small>
    </article>
  );
}

function Cockpit({ cockpit }) {
  return (
    <article className="cockpit">
      <div className="cockpitHead">
        <div>
          <strong>{cockpit.asset_id?.toUpperCase()}</strong>
          <span>{cockpit.horizon} · {cockpit.side}</span>
        </div>
        <span className={stateClass(cockpit.dominant_state)}>{cockpit.dominant_state}</span>
      </div>
      <div className="cockpitGrid">
        <div><span>Qty</span><b>{number(cockpit.quantity, 8)}</b></div>
        <div><span>Entry</span><b>{number(cockpit.average_entry_price, 8)}</b></div>
        <div><span>Mark</span><b>{number(cockpit.mark_price, 8)}</b></div>
        <div><span>Hard stop</span><b>{number(cockpit.hard_stop_price, 8)}</b></div>
      </div>
      <small>{cockpit.position_key}</small>
    </article>
  );
}


const VIEW_META = {
  floor: { title: "Unified Firm Floor", subtitle: "Command central for the autonomous PAPER firm." },
  assets: { title: "Assets", subtitle: "Live stations, strategy state and canonical blockers." },
  pipeline: { title: "Pipeline", subtitle: "See each Firm seat working and where flow is backing up." },
  live: { title: "Live Trades", subtitle: "Open PAPER positions, setup watch and runtime activity." },
  blotter: { title: "Blotter", subtitle: "Completed round trips in the current paper-test epoch." },
  booth: { title: "Booth", subtitle: "Operator visibility, system health and safety state." },
  settings: { title: "Settings", subtitle: "Prototype runtime, data and safety configuration." },
};

function durationLabel(openedAt, nowMs) {
  const started = Date.parse(openedAt || "");
  if (!Number.isFinite(started)) return "—";
  const seconds = Math.max(0, Math.floor((nowMs - started) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  if (hours > 0) return hours + "h " + minutes + "m " + remainder + "s";
  if (minutes > 0) return minutes + "m " + remainder + "s";
  return remainder + "s";
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

function BankStrip({ operator }) {
  const bank = operator?.bank || {};
  const test = operator?.paper_test || {};
  return (
    <section className="bankStrip" aria-label="Paper bank">
      <div><span>Starting bank</span><strong>{money(test.seed_bank_usd)}</strong></div>
      <div><span>Book cash</span><strong>{money(bank.book_cash_usd)}</strong></div>
      <div><span>Available</span><strong>{money(bank.cash_available_usd)}</strong></div>
      <div><span>Reserved</span><strong>{money(bank.cash_reserved_usd)}</strong></div>
      <div><span>Realized P&amp;L</span><strong className={Number(bank.realized_pnl_usd) < 0 ? "lossText" : Number(bank.realized_pnl_usd) > 0 ? "gainText" : ""}>{money(bank.realized_pnl_usd, "$0.00")}</strong></div>
      <div><span>Fees</span><strong>{money(bank.fees_accrued_usd, "$0.00")}</strong></div>
    </section>
  );
}

function ActivityFeed({ rows, limit = 30 }) {
  const items = (rows || []).slice(0, limit);
  if (!items.length) return <Empty>No vNext Firm events in the current test epoch yet.</Empty>;
  return (
    <div className="activityFeed">
      {items.map((row) => (
        <article className="activityRow" key={row.event_id}>
          <time>{timestamp(row.created_at_utc, "—")}</time>
          <div>
            <strong>{text(row.seat, "Firm")} · {text(row.new_state, "EVENT")}</strong>
            <span>{text(row.aggregate_type, "event")} · {text(row.reason_code, "recorded")}</span>
          </div>
          <small>{text(row.aggregate_id)}</small>
        </article>
      ))}
    </div>
  );
}

function AssetsView({ universe, selectedAsset, onSelect, strategyAssets }) {
  return (
    <section className="appView">
      <div className="pageLead">
        <p className="eyebrow">ASSET DESKS</p>
        <h2>Prototype Stations</h2>
        <p>BTC and ETH are the commissioned autonomous prototype assets. Other Firm stations remain fail-closed until their providers are commissioned.</p>
      </div>
      <div className="universeGrid">
        {universe.map((station) => (
          <div className="assetStationWrap" key={station.asset_id}>
            <UniverseCard
              station={station}
              selected={station.asset_id === selectedAsset}
              onSelect={onSelect}
            />
            {strategyAssets?.[station.asset_id] ? (
              <div className="assetStrategyLine">
                <span>Strategy</span>
                <b>{text(strategyAssets[station.asset_id].stage, "WAITING")}</b>
                <small>{text(strategyAssets[station.asset_id].reason, "—")}</small>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function LiveTradesView({ cockpits, strategyAssets, strategy, activity, nowMs }) {
  return (
    <section className="appView">
      <div className="heroGrid compactHero">
        <article><span>Open trades</span><strong>{cockpits.length}</strong></article>
        <article><span>Strategy cycle</span><strong>#{text(strategy?.cycle_count, "0")}</strong></article>
        <article><span>Last scan</span><strong>{timestamp(strategy?.last_cycle_finished_at_utc, "waiting")}</strong></article>
        <article><span>Execution</span><strong>PAPER</strong><small>LIVE BLOCKED</small></article>
      </div>

      <section className="floorSection">
        <div className="sectionHead">
          <div><p className="eyebrow">IN-FLIGHT EXECUTION</p><h2>Active Trade Cockpits</h2></div>
          <span>Timers update every second</span>
        </div>
        {cockpits.length ? (
          <div className="liveCockpitGrid">
            {cockpits.map((row) => (
              <article className="liveTradeCard" key={row.position_key}>
                <div className="tradeCardHead">
                  <div><strong>{row.asset_id?.toUpperCase()}</strong><span>{text(row.horizon)} · {text(row.side)}</span></div>
                  <span className="state good">OPEN</span>
                </div>
                <div className="tradeTimer">{durationLabel(row.opened_at_utc, nowMs)}</div>
                <dl className="tradeMetrics">
                  <div><dt>Entry</dt><dd>{number(row.average_entry_price, 8)}</dd></div>
                  <div><dt>Mark</dt><dd>{number(row.mark_price, 8)}</dd></div>
                  <div><dt>Qty</dt><dd>{number(row.quantity, 8)}</dd></div>
                  <div><dt>Hard stop</dt><dd>{number(row.hard_stop_price, 8)}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        ) : <Empty>No open PAPER trades. AETHER is scanning for a natural setup.</Empty>}
      </section>

      <section className="split">
        <section className="floorSection">
          <div className="sectionHead"><div><p className="eyebrow">SETUP WATCH</p><h2>What AETHER Sees Now</h2></div></div>
          <div className="strategyDecisionGrid">
            <StrategyDecision assetId="btc" row={strategyAssets.btc} />
            <StrategyDecision assetId="eth" row={strategyAssets.eth} />
          </div>
        </section>
        <section className="floorSection">
          <div className="sectionHead"><div><p className="eyebrow">BOT ACTIVITY</p><h2>Firm Event Stream</h2></div></div>
          <ActivityFeed rows={activity} limit={16} />
        </section>
      </section>
    </section>
  );
}

function BlotterView({ rows }) {
  return (
    <section className="appView">
      <div className="pageLead">
        <p className="eyebrow">COMPLETED ROUND TRIPS</p>
        <h2>Blotter</h2>
        <p>Current paper-test epoch only. One row per completed trade.</p>
      </div>
      {rows?.length ? (
        <div className="blotterWrap">
          <table className="blotterTable">
            <thead>
              <tr>
                <th>Closed</th><th>Asset</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Duration</th><th>Gross</th><th>Fees</th><th>Net</th><th>MFE</th><th>MAE</th><th>Exit reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.trade_id}>
                  <td>{timestamp(row.closed_at_utc, "—")}</td>
                  <td><strong>{text(row.asset_id).toUpperCase()}</strong></td>
                  <td>{text(row.side)}</td>
                  <td>{number(row.quantity, 8)}</td>
                  <td>{number(row.avg_entry_price, 8)}</td>
                  <td>{number(row.exit_price, 8)}</td>
                  <td>{durationLabel(row.closed_at_utc ? new Date(Date.parse(row.closed_at_utc) - Number(row.duration_s || 0) * 1000).toISOString() : null, Date.parse(row.closed_at_utc || ""))}</td>
                  <td>{money(row.gross_pnl_usd)}</td>
                  <td>{money(row.fees_usd)}</td>
                  <td className={Number(row.net_pnl_usd) < 0 ? "lossText" : Number(row.net_pnl_usd) > 0 ? "gainText" : ""}>{money(row.net_pnl_usd)}</td>
                  <td>{money(row.mfe_usd)}</td>
                  <td>{money(row.mae_usd)}</td>
                  <td>{text(row.exit_reason)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>No completed trades in the new-system test epoch yet.</Empty>}
    </section>
  );
}

function BoothView({ floor, ingress, strategy, operator }) {
  const build = floor?.build || {};
  return (
    <section className="appView">
      <div className="pageLead">
        <p className="eyebrow">OPERATOR CONTROL ROOM</p>
        <h2>Booth</h2>
        <p>Read-only prototype operations. Trade authority remains server-side.</p>
      </div>
      <div className="settingsGrid">
        <article className="settingsCard">
          <span>Market ingress</span><strong>{ingress?.running ? "RUNNING" : "OFF"}</strong>
          <small>Cycle #{text(ingress?.cycle_count, "0")} · {text(ingress?.last_error, "no error")}</small>
        </article>
        <article className="settingsCard">
          <span>Strategy worker</span><strong>{strategy?.running ? "RUNNING" : "OFF"}</strong>
          <small>Cycle #{text(strategy?.cycle_count, "0")} · {text(strategy?.last_error, "no error")}</small>
        </article>
        <article className="settingsCard">
          <span>Execution mode</span><strong>PAPER ONLY</strong>
          <small>LIVE execution hard blocked</small>
        </article>
        <article className="settingsCard">
          <span>Build</span><strong>{text(build.source_revision?.slice(0, 12), "local")}</strong>
          <small>App restarted {timestamp(floor?.runtime_started_at_utc, "waiting")}</small>
        </article>
        <article className="settingsCard">
          <span>Paper epoch</span><strong>{text(operator?.paper_test?.epoch_id, "not started")}</strong>
          <small>Seed {money(operator?.paper_test?.seed_bank_usd)}</small>
        </article>
        <article className="settingsCard">
          <span>Authority</span><strong>READ ONLY UI</strong>
          <small>No legacy fallback · no order mutation controls</small>
        </article>
      </div>
    </section>
  );
}

function SettingsView({ ingress, strategy, operator, floor }) {
  return (
    <section className="appView">
      <div className="pageLead">
        <p className="eyebrow">APP CONFIGURATION</p>
        <h2>Settings</h2>
        <p>Current prototype configuration. Locked safety laws are intentionally not editable.</p>
      </div>
      <div className="settingsGrid">
        <article className="settingsCard">
          <span>Trading mode</span><strong>PAPER</strong>
          <small>Natural setups only · forced entries OFF</small>
        </article>
        <article className="settingsCard">
          <span>Live execution</span><strong className="lossText">HARD BLOCKED</strong>
          <small>Cannot be enabled from this UI</small>
        </article>
        <article className="settingsCard">
          <span>Commissioned assets</span><strong>BTC · ETH</strong>
          <small>Kraken public market data</small>
        </article>
        <article className="settingsCard">
          <span>Ingress interval</span><strong>{number(ingress?.interval_seconds, 0)}s</strong>
          <small>UI polls runtime telemetry every 5s</small>
        </article>
        <article className="settingsCard">
          <span>Strategy interval</span><strong>{number(strategy?.interval_seconds, 0)}s</strong>
          <small>Completed-bar strategy evaluation</small>
        </article>
        <article className="settingsCard">
          <span>Forward-paper observations</span><strong>{text(strategy?.last_result?.forward_paper_observation_count, "0")}</strong>
          <small>Operational audit only · Phase 18 false</small>
        </article>
        <article className="settingsCard">
          <span>Database</span><strong>vNext BURN-IN</strong>
          <small>{text(operator?.bank?.ledger_count, "0")} isolated sleeve ledger(s)</small>
        </article>
        <article className="settingsCard">
          <span>Source revision</span><strong>{text(floor?.build?.source_revision?.slice(0, 12), "local")}</strong>
          <small>No legacy trading-state fallback</small>
        </article>
      </div>
      <section className="lockedLaw">
        <strong>LOCKED SAFETY LAWS</strong>
        <span>Valid market data · capital/risk admission · instrument caps · PAPER-only execution · LIVE hard block.</span>
      </section>
    </section>
  );
}


const PIPELINE_QUEUE_SEATS = [
  {
    seat: "Scout",
    owned: "WATCH",
    job: "Finds real setups worth watching and passes only qualified opportunities forward.",
  },
  {
    seat: "Sniper",
    owned: "FIRE",
    job: "Confirms trigger timing and converts a watched setup into an actionable entry candidate.",
  },
  {
    seat: "Risk",
    owned: "SIZE / REJECT",
    job: "Sizes risk or rejects the trade when Firm risk laws are not satisfied.",
  },
  {
    seat: "Clerk",
    owned: "READY / REJECT",
    job: "Builds the execution-ready ticket and refuses incomplete or invalid orders.",
  },
  {
    seat: "Portfolio",
    owned: "ORDER",
    job: "Checks portfolio admission and routes an approved PAPER order into the book.",
  },
];

function queueSummary(queues, seat) {
  const rows = (queues || []).filter((row) => row.seat === seat);
  return {
    seat,
    count: rows.reduce((sum, row) => sum + Number(row.count || 0), 0),
    blockers: rows.reduce((sum, row) => sum + Number(row.blocker_count || 0), 0),
    states: rows.map((row) => ({
      state: text(row.state),
      count: Number(row.count || 0),
      blockerCount: Number(row.blocker_count || 0),
      itemIds: row.item_ids || [],
    })),
    itemIds: rows.flatMap((row) => row.item_ids || []),
  };
}

function pipelineBottleneck(queues) {
  const governor = queueSummary(queues, "Governor");
  if (governor.count > 0 || governor.blockers > 0) {
    return {
      seat: "Governor",
      count: governor.count,
      blockers: governor.blockers,
      reason: "Global HALT pressure",
    };
  }

  const candidates = PIPELINE_QUEUE_SEATS
    .map((row) => Object.assign({}, row, queueSummary(queues, row.seat)))
    .filter((row) => row.count > 0 || row.blockers > 0)
    .sort((a, b) => (
      b.blockers - a.blockers
      || b.count - a.count
      || a.seat.localeCompare(b.seat)
    ));

  if (!candidates.length) return null;
  const row = candidates[0];
  return {
    seat: row.seat,
    count: row.count,
    blockers: row.blockers,
    reason: row.blockers > 0
      ? row.blockers + " blocker" + (row.blockers === 1 ? "" : "s")
      : row.count + " item" + (row.count === 1 ? "" : "s") + " waiting",
  };
}

function PipelineStage({ label, job, owned, metricLabel, count, blockers = 0, bottleneck = false, tone = "queue", states = [] }) {
  const active = Number(count || 0) > 0;
  const blocked = Number(blockers || 0) > 0;
  const className = [
    "pipelineStage",
    tone,
    active ? "busy" : "clear",
    blocked ? "blocked" : "",
    bottleneck ? "bottleneck" : "",
  ].filter(Boolean).join(" ");

  return (
    <article className={className}>
      <div className="pipelineStageTop">
        <span>{owned}</span>
        {bottleneck ? <b>BOTTLENECK</b> : blocked ? <b>BLOCKED</b> : active ? <b>WORKING</b> : <b>CLEAR</b>}
      </div>
      <h3>{label}</h3>
      <p>{job}</p>
      <div className="pipelineMetric">
        <strong>{number(count, 0)}</strong>
        <span>{metricLabel}</span>
      </div>
      {tone === "queue" ? (
        <div className="pipelineStateList">
          {states.map((row) => (
            <span key={label + "-" + row.state}>
              <b>{row.state}</b> {row.count}
              {row.blockerCount ? <em>{row.blockerCount} blocked</em> : null}
            </span>
          ))}
          {!states.length ? <span><b>QUEUE</b> 0</span> : null}
        </div>
      ) : null}
    </article>
  );
}

function PipelineView({ universe, queues, cockpits, operator, strategy }) {
  const queueStages = PIPELINE_QUEUE_SEATS.map((stage) => Object.assign(
    {},
    stage,
    queueSummary(queues, stage.seat),
  ));
  const governor = queueSummary(queues, "Governor");
  const bottleneck = pipelineBottleneck(queues);
  const queuedItems = queueStages.reduce((sum, row) => sum + row.count, 0);
  const blockerCount = queueStages.reduce((sum, row) => sum + row.blockers, 0) + governor.blockers;
  const maxQueue = Math.max(1, ...queueStages.map((row) => row.count));
  const completedTrades = Number(operator?.blotter?.length || 0);
  const pipelineStatus = governor.count > 0 || governor.blockers > 0
    ? "GLOBAL HALT"
    : bottleneck
      ? "PRESSURE"
      : "FLOW CLEAR";

  return (
    <section className="appView pipelineView">
      <section className={"pipelineHero " + (bottleneck ? "pressure" : "clear")}>
        <div>
          <p className="eyebrow">LIVE FIRM FLOW</p>
          <h2>{bottleneck ? bottleneck.seat + " is the current pressure point" : "No queue bottleneck detected"}</h2>
          <p>
            {bottleneck
              ? bottleneck.reason + ". This is calculated from current vNext queue and blocker telemetry."
              : "All canonical seat queues are currently clear. AETHER is still scanning for natural setups."}
          </p>
        </div>
        <div className="pipelineHeroStats">
          <span><b>{pipelineStatus}</b> status</span>
          <span><b>{queuedItems}</b> queued</span>
          <span><b>{blockerCount}</b> blockers</span>
          <span><b>{cockpits.length}</b> open positions</span>
        </div>
      </section>

      <section className="governorGate">
        <div>
          <p className="eyebrow">GLOBAL FIRM GATE</p>
          <h3>Governor</h3>
          <p>Can stop downstream flow when a Firm-wide hard condition is active.</p>
        </div>
        <div className={governor.count || governor.blockers ? "governorStatus halted" : "governorStatus clear"}>
          <strong>{governor.count || governor.blockers ? "HALT ACTIVE" : "CLEAR"}</strong>
          <span>{governor.count} queued · {governor.blockers} blockers</span>
        </div>
      </section>

      <section className="floorSection pipelineSection">
        <div className="sectionHead">
          <div><p className="eyebrow">END-TO-END PIPELINE</p><h2>Firm Seats</h2></div>
          <span>Live vNext telemetry · no synthetic work</span>
        </div>

        <div className="pipelineFlow" aria-label="AETHER Firm pipeline">
          <PipelineStage
            label="Universe"
            owned="INPUT"
            job="Maintains the supported asset universe before an opportunity can enter setup discovery."
            metricLabel="assets"
            count={universe.length}
            tone="context"
          />
          {queueStages.map((stage) => (
            <PipelineStage
              key={stage.seat}
              label={stage.seat}
              owned={stage.owned}
              job={stage.job}
              metricLabel="in queue"
              count={stage.count}
              blockers={stage.blockers}
              bottleneck={bottleneck?.seat === stage.seat}
              states={stage.states}
            />
          ))}
          <PipelineStage
            label="Open Position"
            owned="OPEN"
            job="A PAPER trade that passed admission and is now in the managed book."
            metricLabel="open"
            count={cockpits.length}
            tone="context"
          />
          <PipelineStage
            label="Exit"
            owned="MANAGE"
            job="Applies horizon, stop and exit management to the positions currently open."
            metricLabel="managed"
            count={cockpits.length}
            tone="context"
          />
          <PipelineStage
            label="Review"
            owned="CLOSED"
            job="Completed PAPER round trips land in the epoch blotter for post-trade review."
            metricLabel="closed this epoch"
            count={completedTrades}
            tone="context"
          />
        </div>
      </section>

      <section className="floorSection">
        <div className="sectionHead">
          <div><p className="eyebrow">BOTTLENECK LENS</p><h2>Queue Pressure</h2></div>
          <span>Longer bars = more work waiting at that seat</span>
        </div>
        <div className="pipelinePressure">
          {queueStages.map((stage) => {
            const width = stage.count > 0 ? Math.max(8, Math.round((stage.count / maxQueue) * 100)) : 0;
            return (
              <div className={"pressureRow " + (bottleneck?.seat === stage.seat ? "hot" : "")} key={"pressure-" + stage.seat}>
                <div className="pressureLabel">
                  <strong>{stage.seat}</strong>
                  <span>{stage.count} queued · {stage.blockers} blockers</span>
                </div>
                <div className="pressureTrack">
                  <span style={{ width: width + "%" }} />
                </div>
                <b>{stage.count}</b>
              </div>
            );
          })}
        </div>
      </section>

      <section className="split">
        <section className="floorSection">
          <div className="sectionHead"><div><p className="eyebrow">QUEUE CONTENTS</p><h2>What Is Waiting</h2></div></div>
          <div className="pipelineQueueInspector">
            {queueStages.map((stage) => (
              <article key={"inspect-" + stage.seat}>
                <div><strong>{stage.seat}</strong><span>{stage.count} item(s)</span></div>
                {stage.itemIds.length
                  ? <div className="pipelineItemIds">{stage.itemIds.slice(0, 8).map((id) => <code key={id}>{id}</code>)}</div>
                  : <small>Queue clear</small>}
              </article>
            ))}
          </div>
        </section>

        <section className="floorSection">
          <div className="sectionHead"><div><p className="eyebrow">SCANNER FEED</p><h2>Current BTC / ETH Decisions</h2></div></div>
          <div className="strategyDecisionGrid">
            <StrategyDecision assetId="btc" row={strategy?.last_result?.assets?.btc} />
            <StrategyDecision assetId="eth" row={strategy?.last_result?.assets?.eth} />
          </div>
        </section>
      </section>
    </section>
  );
}

function AppSubview({ activeView, universe, queues, selectedAsset, onSelectAsset, cockpits, strategyAssets, strategy, ingress, operator, floor, nowMs }) {
  if (activeView === "assets") {
    return <AssetsView universe={universe} selectedAsset={selectedAsset} onSelect={onSelectAsset} strategyAssets={strategyAssets} />;
  }
  if (activeView === "pipeline") {
    return <PipelineView universe={universe} queues={queues} cockpits={cockpits} operator={operator} strategy={strategy} />;
  }
  if (activeView === "live") {
    return <LiveTradesView cockpits={cockpits} strategyAssets={strategyAssets} strategy={strategy} activity={operator?.activity || []} nowMs={nowMs} />;
  }
  if (activeView === "blotter") {
    return <BlotterView rows={operator?.blotter || []} />;
  }
  if (activeView === "booth") {
    return <BoothView floor={floor} ingress={ingress} strategy={strategy} operator={operator} />;
  }
  if (activeView === "settings") {
    return <SettingsView ingress={ingress} strategy={strategy} operator={operator} floor={floor} />;
  }
  return null;
}

function BottomDock({ activeView, onNavigate }) {
  const items = [
    ["floor", "⌂", "Floor"],
    ["pipeline", "⇢", "Pipeline"],
    ["assets", "◉", "Assets"],
    ["live", "⌁", "Live"],
    ["blotter", "≡", "Blotter"],
    ["booth", "◇", "Booth"],
  ];
  return (
    <nav className="bottomDock" aria-label="Primary">
      {items.map(([id, icon, label]) => (
        <button type="button" className={activeView === id ? "on" : ""} onClick={() => onNavigate(id)} key={id}>
          <span className="dockIcon" aria-hidden="true">{icon}</span>
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

function AppMenu({ open, activeView, onClose, onNavigate, floor, ingress, strategy }) {
  return (
    <>
      <button type="button" className={"menuScrim " + (open ? "open" : "")} onClick={onClose} aria-label="Close menu" />
      <aside className={"appMenu " + (open ? "open" : "")} aria-label="AETHER menu">
        <div className="appMenuHead">
          <div className="menuBrand">
            <img src="/vnext/aether-mark.png" alt="" aria-hidden="true" />
            <div><p className="eyebrow">AETHER</p><h2>Menu</h2></div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close menu">×</button>
        </div>
        {[
          ["settings", "⚙", "Settings", "Runtime, data and safety"],
          ["floor", "⌂", "The Floor", "Portfolio command overview"],
          ["pipeline", "⇢", "Pipeline", "Seat flow and bottleneck visibility"],
          ["live", "●", "Live Trades", "Positions, setup watch and activity"],
          ["blotter", "≡", "Blotter", "Completed PAPER trades"],
          ["assets", "◉", "Assets", "Prototype trading stations"],
          ["booth", "◇", "Booth", "System health and operator visibility"],
        ].map(([id, icon, label, description]) => (
          <button
            type="button"
            className={"appMenuItem " + (activeView === id ? "on" : "")}
            key={id}
            onClick={() => { onNavigate(id); onClose(); }}
          >
            <span>{icon}</span>
            <span><b>{label}</b><small>{description}</small></span>
            <span>›</span>
          </button>
        ))}
        <div className="appMenuStatus">
          <span className={ingress?.running ? "state good" : "state bad"}>INGRESS {ingress?.running ? "RUNNING" : "OFF"}</span>
          <span className={strategy?.running ? "state good" : "state bad"}>STRATEGY {strategy?.running ? "RUNNING" : "OFF"}</span>
          <small>Build {text(floor?.build?.source_revision?.slice(0, 8), "local")}</small>
        </div>
      </aside>
    </>
  );
}


function CompactBlotterPreview({ rows }) {
  const items = (rows || []).slice(0, 6);
  if (!items.length) {
    return <Empty>No completed PAPER trades in this epoch yet.</Empty>;
  }
  return (
    <div className="desktopBlotterPreview">
      {items.map((row) => (
        <article key={"desktop-blotter-" + row.trade_id}>
          <div>
            <strong>{text(row.asset_id).toUpperCase()}</strong>
            <span>{text(row.side)} · {timestamp(row.closed_at_utc, "—")}</span>
          </div>
          <div>
            <small>Net</small>
            <b className={Number(row.net_pnl_usd) < 0 ? "lossText" : Number(row.net_pnl_usd) > 0 ? "gainText" : ""}>
              {money(row.net_pnl_usd)}
            </b>
          </div>
          <div>
            <small>Exit</small>
            <b>{number(row.exit_price, 8)}</b>
          </div>
          <div>
            <small>Reason</small>
            <b>{text(row.exit_reason)}</b>
          </div>
        </article>
      ))}
    </div>
  );
}

function DesktopCommandCenter({ floor, queues, cockpits, operator, ingress, strategy, nowMs }) {
  const bottleneck = pipelineBottleneck(queues);
  const governor = queueSummary(queues, "Governor");
  const queueStages = PIPELINE_QUEUE_SEATS.map((stage) => Object.assign(
    {},
    stage,
    queueSummary(queues, stage.seat),
  ));
  const queued = queueStages.reduce((sum, row) => sum + row.count, 0);
  const blockers = queueStages.reduce((sum, row) => sum + row.blockers, 0) + governor.blockers;
  const strategyAssets = strategy?.last_result?.assets || {};

  return (
    <section className="desktopOnly desktopCommandCenter" aria-label="Desktop command center">
      <div className="desktopCommandHead">
        <div>
          <p className="eyebrow">DESKTOP COMMAND CENTER</p>
          <h2>Everything on the Firm floor</h2>
        </div>
        <div className="desktopCommandBadges">
          <span className={ingress?.running && !ingress?.last_error ? "state good" : "state bad"}>
            DATA {ingress?.running && !ingress?.last_error ? "LIVE" : "FAULT"}
          </span>
          <span className={strategy?.running && !strategy?.last_error ? "state good" : "state bad"}>
            STRATEGY {strategy?.running && !strategy?.last_error ? "RUNNING" : "FAULT"}
          </span>
          <span className="state active">PAPER ONLY</span>
        </div>
      </div>

      <div className="desktopCommandGrid">
        <section className="desktopPanel pipelinePanel">
          <div className="desktopPanelHead">
            <div><span>PIPELINE</span><strong>Firm flow & bottleneck</strong></div>
            <b className={bottleneck ? "pressureTag" : "clearTag"}>
              {bottleneck ? bottleneck.seat + " PRESSURE" : "FLOW CLEAR"}
            </b>
          </div>
          <div className="desktopPipelineSummary">
            {queueStages.map((stage) => (
              <div className={"desktopPipelineSeat " + (bottleneck?.seat === stage.seat ? "hot" : "")} key={"desktop-seat-" + stage.seat}>
                <span>{stage.seat}</span>
                <strong>{stage.count}</strong>
                <small>{stage.blockers} blocked</small>
              </div>
            ))}
          </div>
          <div className="desktopPipelineFooter">
            <span><b>{queued}</b> queued</span>
            <span><b>{blockers}</b> blockers</span>
            <span><b>{cockpits.length}</b> open positions</span>
            <span><b>{governor.count || governor.blockers ? "HALT" : "CLEAR"}</b> governor</span>
          </div>
        </section>

        <section className="desktopPanel systemPanel">
          <div className="desktopPanelHead">
            <div><span>SYSTEM</span><strong>Runtime health</strong></div>
            <b>{text(floor?.build?.source_revision?.slice(0, 8), "local")}</b>
          </div>
          <dl className="desktopSystemList">
            <div><dt>App restarted</dt><dd>{timestamp(floor?.runtime_started_at_utc, "waiting")}</dd></div>
            <div><dt>Floor refreshed</dt><dd>{timestamp(floor?.as_of_utc, "waiting")}</dd></div>
            <div><dt>Ingress</dt><dd>#{text(ingress?.cycle_count, "0")} · {text(ingress?.last_error, "healthy")}</dd></div>
            <div><dt>Strategy</dt><dd>#{text(strategy?.cycle_count, "0")} · next {strategyCountdown(strategy, nowMs)}</dd></div>
            <div><dt>Observations</dt><dd>{text(strategy?.last_result?.forward_paper_observation_count, "0")}</dd></div>
            <div><dt>Epoch</dt><dd>{text(operator?.paper_test?.epoch_id, "not started")}</dd></div>
          </dl>
        </section>

        <section className="desktopPanel strategyPanel">
          <div className="desktopPanelHead">
            <div><span>SCANNER</span><strong>BTC / ETH now</strong></div>
            <b>NATURAL ONLY</b>
          </div>
          <div className="desktopStrategyStack">
            <StrategyDecision assetId="btc" row={strategyAssets.btc} />
            <StrategyDecision assetId="eth" row={strategyAssets.eth} />
          </div>
        </section>

        <section className="desktopPanel activityPanel">
          <div className="desktopPanelHead">
            <div><span>ACTIVITY</span><strong>Latest Firm events</strong></div>
            <b>{(operator?.activity || []).length}</b>
          </div>
          <ActivityFeed rows={operator?.activity || []} limit={10} />
        </section>

        <section className="desktopPanel blotterPanel">
          <div className="desktopPanelHead">
            <div><span>BLOTTER</span><strong>Latest completed trades</strong></div>
            <b>{(operator?.blotter || []).length}</b>
          </div>
          <CompactBlotterPreview rows={operator?.blotter || []} />
        </section>
      </div>
    </section>
  );
}

function MobileCommandStrip({ queues, cockpits, operator, ingress, strategy, nowMs }) {
  const bottleneck = pipelineBottleneck(queues);
  return (
    <section className="mobileOnly mobileCommandStrip" aria-label="Mobile command status">
      <div>
        <span>Flow</span>
        <strong>{bottleneck ? bottleneck.seat : "CLEAR"}</strong>
        <small>{bottleneck ? bottleneck.reason : "no bottleneck"}</small>
      </div>
      <div>
        <span>Open</span>
        <strong>{cockpits.length}</strong>
        <small>PAPER trade(s)</small>
      </div>
      <div>
        <span>Next scan</span>
        <strong>{strategyCountdown(strategy, nowMs)}</strong>
        <small>strategy #{text(strategy?.cycle_count, "0")}</small>
      </div>
      <div>
        <span>Bank</span>
        <strong>{money(operator?.bank?.book_cash_usd, "$0.00")}</strong>
        <small>{ingress?.running ? "market live" : "feed waiting"}</small>
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const [floor, setFloor] = useState(null);
  const [ingress, setIngress] = useState(null);
  const [strategy, setStrategy] = useState(null);
  const [operator, setOperator] = useState(null);
  const [error, setError] = useState("");
  const [runtimeError, setRuntimeError] = useState("");
  const [operatorError, setOperatorError] = useState("");
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [activeView, setActiveView] = useState("floor");
  const [menuOpen, setMenuOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [quoteMoves, setQuoteMoves] = useState({});
  const previousQuotePrices = useRef({});

  useEffect(() => {
    const ticker = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(ticker);
  }, []);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const [floorResult, ingressResult, strategyResult, operatorResult] = await Promise.allSettled([
          getJson(floorPath),
          getJson(ingressPath),
          getJson(strategyPath),
          getJson(operatorPath),
        ]);
        if (!mounted) return;

        if (floorResult.status === "fulfilled") {
          const data = floorResult.value;
          setFloor(data);
          setError("");
          setSelectedAsset((current) => {
            if (current && (data.full_universe || []).some((row) => row.asset_id === current)) {
              return current;
            }
            return null;
          });
        } else {
          setError("Canonical vNext Floor endpoint unavailable.");
        }

        if (ingressResult.status === "fulfilled") {
          const nextIngress = ingressResult.value;
          const rows = nextIngress?.last_result?.quotes || [];
          const nextPrices = {};
          for (const row of rows) {
            const assetId = String(row?.asset_id || "").toLowerCase();
            const price = quotePrice(row);
            if (!assetId || price === null) continue;
            nextPrices[assetId] = price;
          }
          setQuoteMoves((current) => {
            const updated = { ...current };
            for (const [assetId, price] of Object.entries(nextPrices)) {
              const prior = previousQuotePrices.current[assetId];
              if (Number.isFinite(prior) && price !== prior) {
                updated[assetId] = price > prior ? 1 : -1;
              }
            }
            return updated;
          });
          previousQuotePrices.current = nextPrices;
          setIngress(nextIngress);
        }
        if (strategyResult.status === "fulfilled") setStrategy(strategyResult.value);
        if (operatorResult.status === "fulfilled") {
          setOperator(operatorResult.value);
          setOperatorError("");
        } else {
          setOperatorError("vNext operator data is temporarily unavailable.");
        }
        setRuntimeError(
          ingressResult.status === "rejected" || strategyResult.status === "rejected"
            ? "One or more autonomous runtime telemetry endpoints are unavailable."
            : "",
        );
      } catch {
        if (mounted) {
          setError("Canonical vNext Floor endpoint unavailable.");
          setRuntimeError("Autonomous runtime telemetry unavailable.");
          setOperatorError("vNext operator data is temporarily unavailable.");
        }
      }
    };
    load();
    const timer = setInterval(load, 5000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  const universe = floor?.full_universe || [];
  const top12 = floor?.top12_attention || [];
  const queues = floor?.seat_queues || [];
  const cockpits = floor?.open_cockpits || [];

  const selectedStation = useMemo(
    () => universe.find((row) => row.asset_id === selectedAsset) || null,
    [universe, selectedAsset],
  );

  const drawer = floor?.inspection_drawer?.asset_id === selectedAsset
    ? floor.inspection_drawer
    : null;
  const drawerOpen = Boolean(selectedStation);
  const ingressState = runtimeState(ingress?.enabled, ingress?.running, ingress?.last_error);
  const strategyState = runtimeState(strategy?.enabled, strategy?.running, strategy?.last_error);
  const strategyAssets = strategy?.last_result?.assets || {};
  const ingressQuotes = ingress?.last_result?.quotes || [];
  const quoteByAsset = Object.fromEntries(
    ingressQuotes.map((row) => [String(row?.asset_id || "").toLowerCase(), row]),
  );
  const marketRunning = Boolean(ingress?.enabled && ingress?.running && !ingress?.last_error);
  const nextStrategyScan = strategyCountdown(strategy, nowMs);
  const viewMeta = VIEW_META[activeView] || VIEW_META.floor;
  const navigate = (view) => {
    setActiveView(view);
    if (view !== "assets") setSelectedAsset(null);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <main className="floorShell">
      <header className="floorHeader">
        <div className="headerIdentity">
          <button type="button" className="menuButton" onClick={() => setMenuOpen(true)} aria-label="Open AETHER menu">☰</button>
          <img className="brandMark" src="/vnext/aether-mark.png" alt="AETHER" />
          <div>
            <p className="eyebrow">AETHER PROP FIRM</p>
            <h1>{viewMeta.title}</h1>
            <p className="subtle">{viewMeta.subtitle}</p>
          </div>
        </div>
        <div className="modeStack">
          <span className="mode paper">PAPER ONLY</span>
          <span className="mode blocked">LIVE BLOCKED</span>
        </div>
      </header>

      {activeView === "floor" ? (
        <>
      <section className="marketHeartbeat" aria-label="Live market heartbeat">
        <div className="heartbeatLead">
          <span className={`heartbeatDot ${marketRunning ? "running" : ""}`} aria-hidden="true" />
          <div>
            <span>MARKET HEARTBEAT</span>
            <strong>{marketRunning ? "KRAKEN INGEST RUNNING" : "MARKET FEED WAITING"}</strong>
          </div>
        </div>

        <div className="heartbeatQuotes">
          <HeartbeatQuote assetId="btc" row={quoteByAsset.btc} direction={quoteMoves.btc} nowMs={nowMs} />
          <HeartbeatQuote assetId="eth" row={quoteByAsset.eth} direction={quoteMoves.eth} nowMs={nowMs} />
        </div>

        <div className="heartbeatMeta">
          <span><b>Ingress</b> #{text(ingress?.cycle_count, "0")}</span>
          <span><b>Strategy</b> #{text(strategy?.cycle_count, "0")}</span>
          <span><b>Next scan</b> {nextStrategyScan}</span>
          <span><b>Trading</b> NATURAL SETUPS ONLY</span>
        </div>
      </section>

      <section className="statusStrip" aria-label="Floor status">
        <span><b>App restarted</b> {timestamp(floor?.runtime_started_at_utc, "waiting for runtime")}</span>
        <span><b>Data refreshed</b> {timestamp(floor?.as_of_utc, "waiting for vNext")}</span>
        <span title={text(floor?.build?.source_revision, "local build")}><b>Build</b> {text(floor?.build?.source_revision?.slice(0, 8), "local")}</span>
        <span><b>Universe</b> {universe.length}</span>
        <span><b>Attention</b> {top12.length}/12</span>
        <span><b>Open cockpits</b> {cockpits.length}</span>
      </section>

      <section className="testStatus" aria-label="Paper test status">
        <span><b>Test run</b> {text(floor?.paper_test?.epoch_id, "not reset")}</span>
        <span><b>Starting bank</b> ${number(floor?.paper_test?.seed_bank_usd, 2)}</span>
        <span><b>Blotter</b> {text(floor?.paper_test?.blotter_trade_count, "0")} trade(s)</span>
      </section>

      <BankStrip operator={operator} />

      <MobileCommandStrip
        queues={queues}
        cockpits={cockpits}
        operator={operator}
        ingress={ingress}
        strategy={strategy}
        nowMs={nowMs}
      />

      <DesktopCommandCenter
        floor={floor}
        queues={queues}
        cockpits={cockpits}
        operator={operator}
        ingress={ingress}
        strategy={strategy}
        nowMs={nowMs}
      />

      <section className="runtimeMonitor" aria-label="Autonomous prototype runtime">
        <div className="runtimeMonitorHead">
          <div>
            <p className="eyebrow">AUTONOMOUS PAPER ENGINE</p>
            <h2>Live Strategy Monitor</h2>
          </div>
          <div className="runtimeBadges">
            <span className={ingressState.className}>INGRESS {ingressState.label}</span>
            <span className={strategyState.className}>STRATEGY {strategyState.label}</span>
          </div>
        </div>

        <div className="runtimeMetrics">
          <div><span>Ingress cycles</span><b>{text(ingress?.cycle_count, "0")}</b></div>
          <div><span>Strategy cycles</span><b>{text(strategy?.cycle_count, "0")}</b></div>
          <div><span>Forward-paper observations</span><b>{text(strategy?.last_result?.forward_paper_observation_count, "0")}</b></div>
          <div><span>Last strategy cycle</span><b>{timestamp(strategy?.last_cycle_finished_at_utc, "waiting")}</b></div>
          <div><span>Last error</span><b className={strategy?.last_error ? "runtimeFault" : ""}>{text(strategy?.last_error, "none")}</b></div>
        </div>

        <div className="strategyDecisionGrid">
          <StrategyDecision assetId="btc" row={strategyAssets.btc} />
          <StrategyDecision assetId="eth" row={strategyAssets.eth} />
        </div>
        <p className="runtimeLaw">
          Read-only telemetry. Natural setups only. PAPER execution only. LIVE remains hard blocked.
        </p>
      </section>

      {runtimeError ? (
        <section className="apiNotice">
          <strong>RUNTIME TELEMETRY DEGRADED</strong>
          <span>{runtimeError}</span>
          <small>Trading controls remain server-side; this panel is inspection only.</small>
        </section>
      ) : null}

      {error ? (
        <section className="apiNotice">
          <strong>READ-ONLY FLOOR WAITING</strong>
          <span>{error}</span>
          <small>No legacy fallback and no placeholder trading state is substituted.</small>
        </section>
      ) : null}

      <section className="floorSection">
        <div className="sectionHead">
          <div><p className="eyebrow">ATTENTION BOARD</p><h2>Top 12 Attention</h2></div>
          <span>Rank supplied by canonical upstream state</span>
        </div>
        {top12.length ? (
          <div className="attentionGrid">
            {top12.map((row) => (
              <button
                type="button"
                className="attentionRow"
                key={`${row.rank}:${row.asset_id}`}
                onClick={() => setSelectedAsset(row.asset_id)}
              >
                <b>#{row.rank}</b>
                <strong>{row.asset_id?.toUpperCase()}</strong>
                <span className={stateClass(row.dominant_state)}>{row.dominant_state}</span>
                <span>{row.seat_owner}</span>
                <small>{text(row.first_blocker, "clear")}</small>
              </button>
            ))}
          </div>
        ) : <Empty>No ranked attention snapshot yet.</Empty>}
      </section>

      <section className="floorSection">
        <div className="sectionHead">
          <div><p className="eyebrow">ALL SUPPORTED ASSETS</p><h2>Full Universe</h2></div>
          <span>Dominant state · owner seat · first blocker</span>
        </div>
        {universe.length ? (
          <div className="universeGrid">
            {universe.map((station) => (
              <UniverseCard
                station={station}
                selected={station.asset_id === selectedAsset}
                onSelect={setSelectedAsset}
                key={station.asset_id}
              />
            ))}
          </div>
        ) : <Empty>No canonical universe snapshot yet.</Empty>}
      </section>

      <section className="split">
        <section className="floorSection">
          <div className="sectionHead">
            <div><p className="eyebrow">FIRM WORKFLOW</p><h2>Seat Queues</h2></div>
          </div>
          {queues.length ? (
            <div className="queueGrid">{queues.map((queue) => <Queue queue={queue} key={`${queue.seat}:${queue.state}`} />)}</div>
          ) : <Empty>No queue snapshot yet.</Empty>}
        </section>

        <section className="floorSection">
          <div className="sectionHead">
            <div><p className="eyebrow">OPEN RISK</p><h2>Open Position Cockpits</h2></div>
          </div>
          {cockpits.length ? (
            <div className="cockpitList">{cockpits.map((cockpit) => <Cockpit cockpit={cockpit} key={cockpit.position_key} />)}</div>
          ) : <Empty>No open positions.</Empty>}
        </section>
      </section>
        </>
      ) : (
        <AppSubview
          activeView={activeView}
          universe={universe}
          queues={queues}
          selectedAsset={selectedAsset}
          onSelectAsset={setSelectedAsset}
          cockpits={cockpits}
          strategyAssets={strategyAssets}
          strategy={strategy}
          ingress={ingress}
          operator={operator}
          floor={floor}
          nowMs={nowMs}
        />
      )}

      {operatorError ? (
        <section className="apiNotice">
          <strong>OPERATOR DATA DEGRADED</strong>
          <span>{operatorError}</span>
          <small>The app never substitutes legacy trading state.</small>
        </section>
      ) : null}

      <aside className={`inspectionDrawer ${drawerOpen ? "open" : ""}`} aria-label="Inspection Drawer">
        <div className="drawerHead">
          <div><p className="eyebrow">READ-ONLY INSPECTION</p><h2>Inspection Drawer</h2></div>
          <button type="button" onClick={() => setSelectedAsset(null)} aria-label="Close inspection drawer">×</button>
        </div>
        {selectedStation ? (
          <>
            <div className="drawerAsset">
              <strong>{selectedStation.asset_id?.toUpperCase()}</strong>
              <span className={stateClass(selectedStation.dominant_state)}>{text(selectedStation.dominant_state, "NO")}</span>
            </div>
            <dl className="drawerList">
              <div><dt>Seat owner</dt><dd>{text(selectedStation.seat_owner)}</dd></div>
              <div><dt>First blocker</dt><dd>{text(selectedStation.first_blocker, "clear")}</dd></div>
              <div><dt>First blocker reason</dt><dd>{text(selectedStation.first_blocker_reason)}</dd></div>
              <div><dt>Open positions</dt><dd>{text(selectedStation.open_position_count, "0")}</dd></div>
            </dl>
            {drawer ? (
              <dl className="drawerList canonicalDetails">
                <div><dt>Observation</dt><dd>{text(drawer.market_observation_ref)}</dd></div>
                <div><dt>Decision lineage</dt><dd>{text(drawer.decision_lineage_ref)}</dd></div>
                <div><dt>Evidence refs</dt><dd>{(drawer.evidence_refs || []).join(", ") || "—"}</dd></div>
                <div><dt>Blocker refs</dt><dd>{(drawer.blocker_refs || []).join(", ") || "—"}</dd></div>
              </dl>
            ) : (
              <Empty>Canonical lineage drawer details are unavailable for this station in the current snapshot.</Empty>
            )}
            <p className="drawerLaw">Inspection only. No order, Risk, Governor, or route-state mutation controls are exposed here.</p>
          </>
        ) : <Empty>Select an asset station to inspect it.</Empty>}
      </aside>

      <AppMenu
        open={menuOpen}
        activeView={activeView}
        onClose={() => setMenuOpen(false)}
        onNavigate={navigate}
        floor={floor}
        ingress={ingress}
        strategy={strategy}
      />
      <BottomDock activeView={activeView} onNavigate={navigate} />
    </main>
  );
}
