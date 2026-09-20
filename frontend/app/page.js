const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function getJson(path) {
  try {
    const res = await fetch(`${apiBase}${path}`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function DashboardPage() {
  const health = await getJson("/api/v1/health");
  const account = await getJson("/api/v1/account");
  const bot = await getJson("/api/v1/bot");

  return (
    <main className="shell">
      <header className="header">
        <strong>PROJECT AETHER — BTC TRADING DASHBOARD</strong>
        <span className="badge">{health?.env === "live" ? "LIVE" : "PAPER"}</span>
      </header>

      <section className="card" style={{ marginTop: 12 }}>
        <h2>[1] ACCOUNT SUMMARY AND WALLET</h2>
        <div className="row"><span>Available USD</span><span>{account?.usd_free ?? "-"}</span></div>
        <div className="row"><span>BTC holdings</span><span>{account?.btc_total ?? "-"}</span></div>
        <div className="row"><span>Equity</span><span>{account?.equity_usd ?? "-"}</span></div>
        <div className="row"><span>Open P/L</span><span>{account?.open_pnl ?? "-"}</span></div>
        <div className="row"><span>Margin utilized</span><span>0% (spot)</span></div>
      </section>

      <div className="grid grid-2">
        <section className="card">
          <h2>[2] LIVE TICKER AND CHART</h2>
          <p>Venue tape and candles arrive in Phase 1. Health: {health?.ok ? "API up" : "API unreachable"}.</p>
          <p className="log">venue_ws: {health?.venue_ws || "unknown"}</p>
        </section>
        <section className="card">
          <h2>[3] BOT CONTROL AND STRATEGY</h2>
          <div className="row"><span>State</span><span>{bot?.state || "UNKNOWN"}</span></div>
          <div className="row"><span>Strategy</span><span>{bot?.strategy || "sma_crossover"}</span></div>
          <div className="row"><span>Paper mode</span><span>{String(bot?.paper_mode ?? true)}</span></div>
          <p className="log">{bot?.reason}</p>
          <div className="actions">
            <button type="button" disabled>Start</button>
            <button type="button" disabled>Stop</button>
          </div>
        </section>
      </div>

      <section className="card">
        <h2>[4] MANUAL OVERRIDE AND EXECUTION TERMINAL</h2>
        <div className="actions">
          <button type="button" disabled>Buy Market</button>
          <button type="button" disabled>Sell Market</button>
          <button type="button" className="danger" disabled>Emergency Flatten</button>
        </div>
        <p className="log">Execution routes are intentionally disabled in Phase 0.</p>
      </section>

      <section className="card">
        <h2>[5] SYSTEM AUDIT AND EXECUTION LOG</h2>
        <div className="log">
          INFO Phase 0 shell loaded.{"\n"}
          INFO Bot remains OFFLINE until an operator arms it.{"\n"}
          INFO No venue keys required to render this page.
        </div>
      </section>
    </main>
  );
}
