"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "";
const floorPath = process.env.NEXT_PUBLIC_AETHER_FLOOR_PATH || "/api/v1/vnext/floor";
const ingressPath = "/api/v1/vnext/ingress-runtime";
const strategyPath = "/api/v1/vnext/strategy-runtime";

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

export default function DashboardPage() {
  const [floor, setFloor] = useState(null);
  const [ingress, setIngress] = useState(null);
  const [strategy, setStrategy] = useState(null);
  const [error, setError] = useState("");
  const [runtimeError, setRuntimeError] = useState("");
  const [selectedAsset, setSelectedAsset] = useState(null);
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
        const [floorResult, ingressResult, strategyResult] = await Promise.allSettled([
          getJson(floorPath),
          getJson(ingressPath),
          getJson(strategyPath),
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
        setRuntimeError(
          ingressResult.status === "rejected" || strategyResult.status === "rejected"
            ? "One or more autonomous runtime telemetry endpoints are unavailable."
            : "",
        );
      } catch {
        if (mounted) {
          setError("Canonical vNext Floor endpoint unavailable.");
          setRuntimeError("Autonomous runtime telemetry unavailable.");
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

  return (
    <main className="floorShell">
      <header className="floorHeader">
        <div>
          <p className="eyebrow">PROJECT AETHER · FIRM</p>
          <h1>Unified Firm Floor</h1>
          <p className="subtle">One Firm. Full universe. Canonical seat ownership.</p>
        </div>
        <div className="modeStack">
          <span className="mode paper">PAPER ONLY</span>
          <span className="mode blocked">LIVE BLOCKED</span>
        </div>
      </header>

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
    </main>
  );
}
