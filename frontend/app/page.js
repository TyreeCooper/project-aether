"use client";

import { useCallback, useEffect, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

function authHeaders(token, stepUp = "") {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (stepUp) headers["X-Aether-Step-Up"] = stepUp;
  return headers;
}

async function getJson(path, token = "") {
  const res = await fetch(`${apiBase}${path}`, {
    cache: "no-store",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`${res.status}:${path}`);
  return res.json();
}

async function post(path, token = "", stepUp = "") {
  const res = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: authHeaders(token, stepUp),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.detail || `${res.status}:${path}`);
  return body;
}

function fmt(value, digits = 2) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

export default function DashboardPage() {
  const [health, setHealth] = useState(null);
  const [account, setAccount] = useState(null);
  const [bot, setBot] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [venueReadiness, setVenueReadiness] = useState(null);
  const [audit, setAudit] = useState([]);
  const [operatorToken, setOperatorToken] = useState("");
  const [stepUpToken, setStepUpToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const h = await getJson("/api/v1/health");
      setHealth(h);

      if (!operatorToken) {
        setError("Operator authentication required for trading data and controls.");
        return;
      }

      const [a, b, p, log, venue] = await Promise.all([
        getJson("/api/v1/account", operatorToken),
        getJson("/api/v1/bot", operatorToken),
        getJson("/api/v1/performance", operatorToken),
        getJson("/api/v1/audit", operatorToken),
        getJson("/api/v1/venue/kraken/readiness", operatorToken),
      ]);
      setAccount(a);
      setBot(b);
      setPerformance(p);
      setAudit(log.events || []);
      setVenueReadiness(venue);
      setError("");
    } catch (err) {
      const message = String(err?.message || err);
      setError(
        message.startsWith("401")
          ? "Operator authentication failed."
          : "API request failed. Verify backend and operator credentials."
      );
    }
  }, [operatorToken]);

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
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setBusy(false);
    }
  };

  const pnlClass = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
  const authenticated = Boolean(operatorToken);
  const steppedUp = Boolean(operatorToken && stepUpToken);

  return (
    <main className="shell">
      <header className="header">
        <strong>PROJECT AETHER — BTC PAPER</strong>
        <span className="badge">PAPER</span>
      </header>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[0] OPERATOR SECURITY</h2>
        <div className="auth-grid">
          <label>
            <span>Operator token</span>
            <input
              type="password"
              autoComplete="off"
              value={operatorToken}
              onChange={(e) => setOperatorToken(e.target.value)}
              placeholder="Bearer token"
            />
          </label>
          <label>
            <span>Step-up token</span>
            <input
              type="password"
              autoComplete="off"
              value={stepUpToken}
              onChange={(e) => setStepUpToken(e.target.value)}
              placeholder="Required to arm, trade, or unlock"
            />
          </label>
        </div>
        <p className="muted">
          Credentials stay in this browser tab state and are not bundled into the frontend.
        </p>
      </section>

      {error ? <p className="down">{error}</p> : null}

      <div className="grid grid-2">
        <section className="card">
          <h2>[1] SYSTEM STATE</h2>
          <div className="row"><span>API</span><span>{health?.ok ? "ONLINE" : "UNKNOWN"}</span></div>
          <div className="row"><span>Operator auth</span><span>{authenticated ? "PRESENT" : "REQUIRED"}</span></div>
          <div className="row"><span>Step-up</span><span>{steppedUp ? "PRESENT" : "NOT PRESENT"}</span></div>
          <div className="row"><span>State</span><span>{bot?.state || "UNKNOWN"}</span></div>
          <div className="row"><span>Data source</span><span>{account?.mark_source || "-"}</span></div>
          <div className="row"><span>Tick age</span><span>{health?.last_tick_age_ms ?? "-"} ms</span></div>
          <div className="row"><span>Live blocked</span><span>{String(bot?.live_blocked)}</span></div>
          <div className="row"><span>Flatten lock</span><span>{String(bot?.flatten_lock)}</span></div>
          <div className="row"><span>Shadow mode</span><span>{bot?.shadow_mode_enabled ? "ENABLED" : "DISABLED"}</span></div>
          <div className="row"><span>Shadow decisions</span><span>{bot?.shadow_decision_count ?? 0}</span></div>
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
          <p>Public BTC/USD feed. Bars: {bot?.bars ?? 0}/{bot?.warm_up_needed ?? 22}.</p>
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
        <h2>[6] VENUE READINESS</h2>
        <div className="row"><span>Read-only credentials</span><span>{venueReadiness?.configured ? "CONFIGURED" : "NOT CONFIGURED"}</span></div>
        <div className="row"><span>Readiness</span><span>{venueReadiness?.ready ? "READY" : "NOT READY"}</span></div>
        <div className="row"><span>IP allowlist</span><span>{venueReadiness?.ip_allowlist_configured ? "CONFIGURED" : "-"}</span></div>
        <div className="row"><span>Venue BTC</span><span>{venueReadiness?.btc_balance ?? "-"}</span></div>
        <div className="row"><span>Last reconciliation</span><span>{bot?.last_reconciliation_ok == null ? "-" : bot.last_reconciliation_ok ? "MATCHED" : "MISMATCH"}</span></div>
        <div className="row"><span>Reconcile age</span><span>{bot?.last_reconciliation_age_ms == null ? "-" : `${bot.last_reconciliation_age_ms} ms`}</span></div>
        <div className="row"><span>Required to arm</span><span>{String(bot?.venue_reconciliation_required)}</span></div>
        <div className="actions">
          <button
            type="button"
            disabled={busy || !authenticated || !venueReadiness?.configured}
            onClick={() => act(() => post("/api/v1/venue/kraken/reconcile", operatorToken))}
          >
            Reconcile venue
          </button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[7] BOT CONTROLS</h2>
        <div className="actions">
          <button type="button" disabled={busy || !steppedUp} onClick={() => act(() => post("/api/v1/bot/start", operatorToken, stepUpToken))}>Start</button>
          <button type="button" disabled={busy || !authenticated} onClick={() => act(() => post("/api/v1/bot/stop", operatorToken))}>Stop</button>
          <button type="button" disabled={busy || !steppedUp} onClick={() => act(() => post("/api/v1/risk/unlock", operatorToken, stepUpToken))}>Unlock</button>
          <button type="button" disabled={busy || !steppedUp || bot?.state !== "FAULT"} onClick={() => act(() => post("/api/v1/risk/reset-fault", operatorToken, stepUpToken))}>Reset fault</button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[8] MANUAL PAPER TICKETS</h2>
        <div className="actions">
          <button type="button" disabled={busy || !steppedUp} onClick={() => act(() => post("/api/v1/orders/market?side=buy", operatorToken, stepUpToken))}>Buy market</button>
          <button type="button" disabled={busy || !steppedUp} onClick={() => act(() => post("/api/v1/orders/market?side=sell", operatorToken, stepUpToken))}>Sell market</button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 10 }}>
        <h2>[9] AUDIT</h2>
        <div className="log">
          {(audit.length ? audit : [{ ts: "", level: "INFO", message: "Waiting for authenticated engine data" }])
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
        <button
          type="button"
          className="danger"
          disabled={busy || !authenticated}
          onClick={() => act(() => post("/api/v1/orders/flatten", operatorToken))}
        >
          Emergency flatten
        </button>
      </div>
    </main>
  );
}
