"use client";

import { useEffect, useMemo, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const floorPath = process.env.NEXT_PUBLIC_AETHER_FLOOR_PATH || "/api/v1/vnext/floor";

async function getJson(path) {
  const response = await fetch(`${apiBase}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

function text(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function number(value, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
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
  const [error, setError] = useState("");
  const [selectedAsset, setSelectedAsset] = useState(null);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await getJson(floorPath);
        if (!mounted) return;
        setFloor(data);
        setError("");
        setSelectedAsset((current) => {
          if (current && (data.full_universe || []).some((row) => row.asset_id === current)) {
            return current;
          }
          return data.inspection_drawer?.asset_id || data.top12_attention?.[0]?.asset_id || data.full_universe?.[0]?.asset_id || null;
        });
      } catch {
        if (mounted) setError("Canonical vNext Floor endpoint unavailable.");
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
    : selectedStation
      ? {
          asset_id: selectedStation.asset_id,
          station_ref: `station:${selectedStation.asset_id}`,
          market_observation_ref: null,
          decision_lineage_ref: null,
          evidence_refs: [],
          blocker_refs: selectedStation.first_blocker ? [selectedStation.first_blocker] : [],
          read_only: true,
        }
      : null;

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

      <section className="statusStrip" aria-label="Floor status">
        <span><b>Snapshot</b> {text(floor?.as_of_utc, "waiting for vNext")}</span>
        <span><b>Universe</b> {universe.length}</span>
        <span><b>Attention</b> {top12.length}/12</span>
        <span><b>Open cockpits</b> {cockpits.length}</span>
      </section>

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

      <aside className={`inspectionDrawer ${drawer ? "open" : ""}`} aria-label="Inspection Drawer">
        <div className="drawerHead">
          <div><p className="eyebrow">READ-ONLY INSPECTION</p><h2>Inspection Drawer</h2></div>
          <button type="button" onClick={() => setSelectedAsset(null)} aria-label="Close inspection drawer">×</button>
        </div>
        {drawer ? (
          <>
            <div className="drawerAsset">
              <strong>{drawer.asset_id?.toUpperCase()}</strong>
              <span className={stateClass(selectedStation?.dominant_state)}>{text(selectedStation?.dominant_state, "NO")}</span>
            </div>
            <dl className="drawerList">
              <div><dt>Seat owner</dt><dd>{text(selectedStation?.seat_owner)}</dd></div>
              <div><dt>First blocker</dt><dd>{text(selectedStation?.first_blocker, "clear")}</dd></div>
              <div><dt>Observation</dt><dd>{text(drawer.market_observation_ref)}</dd></div>
              <div><dt>Decision lineage</dt><dd>{text(drawer.decision_lineage_ref)}</dd></div>
              <div><dt>Evidence refs</dt><dd>{(drawer.evidence_refs || []).join(", ") || "—"}</dd></div>
              <div><dt>Blocker refs</dt><dd>{(drawer.blocker_refs || []).join(", ") || "—"}</dd></div>
            </dl>
            <p className="drawerLaw">Inspection only. No order, Risk, Governor, or route-state mutation controls are exposed here.</p>
          </>
        ) : <Empty>Select an asset station to inspect it.</Empty>}
      </aside>
    </main>
  );
}
