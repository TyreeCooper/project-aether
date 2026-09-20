"use client";

import { useCallback, useEffect, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function getJson(path) {
  const res = await fetch(`${apiBase}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(path);
  return res.json();
}

async function post(path) {
  const res = await fetch(`${apiBase}${path}`, { method: "POST" });
  return res.json();
}

function fmt(value, digits = 2) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

export default function DashboardPage() {
  const [health, setHealth] = useState(null);
  const [account, setAccount] = useState(null);
  const [bot, setBot] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [audit, setAudit] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [h, a, b, p, log] = await Promise.all([
        getJson("/api/v1/health"),
        getJson("/api/v1/account"),
        getJson("/api/v1/bot"),
        getJson("/api/v1/performance"),
        getJson("/api/v1/audit"),
      ]);
      setHealth(h);
      setAccount(a);
      setBot(b);
      setPerformance(p);
      setAudit(log.events || []);
      setError("");
    } catch {
      setError("API unreachable. Start the backend on port 8000.");
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const act = async (fn) => {
    setBusy(true);
    try {
      const result = await fn();
      if (result && result.ok === false) setError(result.error || "denied");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const pnlClass = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");

  return (
    <main className="shell">
      <header className="header">
        <strong>PROJECT AETHER — BTC PAPER</strong>
        <span className="badge">PAPER</span>
      </header>

      {error ? <p className="down">{error}</p> : null}

      <div className="grid grid-2">
        <section className="card">
          <h2>[1] SYSTEM STATE</h2>
          <div className="row"><span>State</span><span>{bot?.state || "UNKNOWN"}</span></div>
          <div className="row"><span>Data source</span><span>{account?.mark_source || "-"}</span></div>
          <div className="row"><span>Tick age</span><span>{health?.last_tick_age_ms ?? "-"} ms</span></div>
          <div className="row"><span>Live blocked</span><span>{String(bot?.live_blocked)}</span></div>
          <div className="row"><span>Flatten lock</span><span>{String(bot?.flatten_lock)}</span></div>
        </section>

        <section className="card">
          <h2>[2] ACCOUNT</h2>
          <div className="row"><span>Mark</span><span>{account?.mark ?? "-"}</span></div>
          <div className="row"><span>USD</span><span>{account?.usd_free ?? "-"}</span></div>
          <div className="row"><span>BTC</span><span>{account?.btc_total ?? "-"}</span></div>
          <div className="row"><span>Equity</span><span>{account?.equity_usd ?? "-"}</span></div>
          <div className="row"><span>Open P/L</span><span className={pnlClass(account?.open_pnl)}>{account?.open_pnl ?? "-"}</span></div>
          <div className="row"><span>Net realized</span><span className={pnlClass(account?.realized_pnl_session)}>{account?.realized_pnl_session ?? "-"}</span></div>
        </section>
      </div>

      <div className="grid grid-2">
        <section className="card">
          <h2>[3] STRATEGY — SMA {bot?.short_ma}/{bot?.long_ma}</h2>
          <p>Public BTC/USD poll every 15s. Bars: {bot?.bars ?? 0}/{bot?.warm_up_needed ?? 22}.</p>
          <div className="row"><span>SMA short</span><span>{bot?.short_value ? Number(bot.short_value).toFixed(2) : "-"}</span></div>
          <div className="row"><span>SMA long</span><span>{bot?.long_value ? Number(bot.long_value).toFixed(2) : "-"}</span></div>
          <div className="row"><span>Profitability gate</span><span>{bot?.profitability_enforced ? "ENFORCED" : "ADVISORY"}</span></div>
          <div className="row"><span>Last edge check</span><span>{bot?.last_profitability_reason || "-"}</span></div>
          <div className="row"><span>Min required</span><span>{bot?.last_minimum_required_bps == null ? "-" : `${fmt(bot.last_minimum_required_bps)} bps`}</span></div>
        </section>

        <section className="card">
          <h2>[4] RISK / PERFORMANCE</h2>
          <div className="row"><span>Daily realized</span><span className={pnlClass(performance?.daily_realized_pnl)}>{fmt(performance?.daily_realized_pnl)}</span></div>
          <div className="row"><span>Gross realized</span><span className={pnlClass(performance?.gross_realized_pnl)}>{fmt(performance?.gross_realized_pnl)}</span></div>
          <div className="row"><span>Max drawdown</span><span>{fmt(performance?.max_drawdown_pct)}%</span></div>
          <div className="row"><span>Closed trades</span><span>{performance?.closed_trade_count ?? 0}</span></div>
          <div className="row"><span>Win rate</span><span>{performance?.win_rate_pct == null ? "-" : `${fmt(performance.win_rate_pct)}%`}</span></div>
          <div className="row"><span>Avg winner</span><span className="up">{fmt(performance?.avg_winner)}</span></div>
          <div className="row"><span>Avg loser</span><span className="down">{fmt(performance?.avg_loser)}</span></div>
        </section>
      </div>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[5] EXECUTION COSTS</h2>
        <div className="row"><span>Fees</span><span>{fmt(performance?.total_fees)}</span></div>
        <div className="row"><span>Spread cost</span><span>{fmt(performance?.total_spread_cost)}</span></div>
        <div className="row"><span>Slippage cost</span><span>{fmt(performance?.total_slippage_cost)}</span></div>
      </section>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[6] BOT CONTROLS</h2>
        <div className="actions">
          <button type="button" disabled={busy} onClick={() => act(() => post("/api/v1/bot/start"))}>Start</button>
          <button type="button" disabled={busy} onClick={() => act(() => post("/api/v1/bot/stop"))}>Stop</button>
          <button type="button" disabled={busy} onClick={() => act(() => post("/api/v1/risk/unlock"))}>Unlock</button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[7] MANUAL PAPER TICKETS</h2>
        <div className="actions">
          <button type="button" disabled={busy} onClick={() => act(() => post("/api/v1/orders/market?side=buy"))}>Buy market</button>
          <button type="button" disabled={busy} onClick={() => act(() => post("/api/v1/orders/market?side=sell"))}>Sell market</button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[8] AUDIT</h2>
        <div className="log">
          {(audit.length ? audit : [{ ts: "", level: "INFO", message: "Waiting for engine" }])
            .slice(0, 25)
            .map((e) => {
              const t = e.ts ? e.ts.slice(11, 19) : "";
              const component = e.component ? ` [${e.component}]` : "";
              return `${t} ${e.level}${component} ${e.message}`;
            })
            .join("\n")}
        </div>
      </section>

      <div className="dock">
        <button type="button" className="danger" disabled={busy} onClick={() => act(() => post("/api/v1/orders/flatten"))}>
          Emergency flatten
        </button>
      </div>
    </main>
  );
}
