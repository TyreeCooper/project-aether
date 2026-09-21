(function(){
  if(document.getElementById("strategyDiagnostics")) return;

  const moneySafe=n=>{
    const v=Number(n);
    if(!Number.isFinite(v)) return "—";
    if(typeof money==="function") return money(v);
    return (v<0?"-$":"$")+Math.abs(v).toFixed(2);
  };
  const pct=n=>{
    const v=Number(n);
    return Number.isFinite(v)?v.toFixed(3)+"%":"—";
  };
  const num=n=>{
    const v=Number(n);
    return Number.isFinite(v)?v.toFixed(3):"—";
  };
  const when=v=>{
    if(!v) return "—";
    const d=new Date(v);
    return Number.isNaN(d.getTime())?String(v):d.toLocaleString();
  };
  const text=(id,value)=>{
    const el=document.getElementById(id);
    if(el) el.textContent=value==null?"—":String(value);
  };
  const tone=(el,value)=>{
    if(!el) return;
    el.classList.remove("goodText","badText","warnText");
    const v=Number(value);
    if(!Number.isFinite(v)||Math.abs(v)<1e-9) return;
    el.classList.add(v>0?"goodText":"badText");
  };
  const regimeClass=regime=>{
    const r=String(regime||"").toLowerCase();
    if(r==="trend") return "good";
    if(r==="chop"||r==="error") return "bad";
    if(r==="warming"||r==="nontrend") return "warn";
    return "";
  };
  const reasonLabel=reason=>String(reason||"—").replaceAll("_"," ").toUpperCase();

  const style=document.createElement("style");
  style.textContent=`
    .strategy-strip{margin-top:9px;padding:8px 10px;border:1px solid rgba(153,146,171,.12);border-radius:10px;background:#0c0a12;font:600 10px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted)}
    .strategy-strip strong{color:var(--text);font-weight:700}
    .diag-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
    .diag-section{margin-top:10px;padding-top:8px;border-top:1px solid rgba(153,146,171,.08)}
    .diag-section:first-of-type{margin-top:0;padding-top:0;border-top:0}
    .diag-label{font-size:9px;letter-spacing:.08em;color:var(--muted);text-transform:uppercase;margin-bottom:6px}
    .diag-mini{padding:9px;border-radius:10px;background:#0c0a12;border:1px solid rgba(153,146,171,.1);min-width:0}
    .diag-mini .k{font-size:8px;color:var(--muted);letter-spacing:.07em;text-transform:uppercase}
    .diag-mini .v{font-size:12px;font-weight:650;margin-top:3px;overflow-wrap:anywhere}
    .diag-foot{margin-top:8px;font-size:10px;color:var(--muted);line-height:1.45}
    @media(max-width:720px){.diag-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;
  document.head.appendChild(style);

  const home=document.getElementById("page-home");
  if(!home) return;
  const engineCard=[...home.querySelectorAll(".card")].find(card=>{
    const h=card.querySelector(".card-head h2");
    return h&&h.textContent.trim()==="AUTONOMOUS ENGINE";
  });
  if(engineCard&&!document.getElementById("strategyStrip")){
    const strip=document.createElement("div");
    strip.id="strategyStrip";
    strip.className="strategy-strip";
    strip.innerHTML='<strong>STRATEGY</strong> · waiting for diagnostics';
    engineCard.appendChild(strip);
  }

  const card=document.createElement("section");
  card.className="card full";
  card.id="strategyDiagnostics";
  card.innerHTML=`
    <div class="card-head">
      <h2>STRATEGY STATUS / DIAGNOSTICS</h2>
      <span id="diagRegimeBadge" class="pill">CHECKING</span>
    </div>

    <div class="diag-section">
      <div class="diag-grid">
        <div class="diag-mini"><div class="k">Strategy</div><div id="diagStrategy" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Regime</div><div id="diagRegime" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Reason</div><div id="diagReason" class="v">—</div></div>
        <div class="diag-mini"><div class="k">State</div><div id="diagState" class="v">—</div></div>
      </div>
    </div>

    <div class="diag-section">
      <div class="diag-label">Bars / Trend</div>
      <div class="diag-grid">
        <div class="diag-mini"><div class="k">1m bars</div><div id="diagBars1" class="v">—</div></div>
        <div class="diag-mini"><div class="k">5m bars</div><div id="diagBars5" class="v">—</div></div>
        <div class="diag-mini"><div class="k">15m bars</div><div id="diagBars15" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Efficiency</div><div id="diagEfficiency" class="v">—</div></div>
        <div class="diag-mini"><div class="k">5m Fast / Slow</div><div id="diag5m" class="v">—</div></div>
        <div class="diag-mini"><div class="k">15m Fast / Slow</div><div id="diag15m" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Breakout</div><div id="diagBreakout" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Breakout level</div><div id="diagBreakoutLevel" class="v">—</div></div>
      </div>
    </div>

    <div class="diag-section">
      <div class="diag-label">Cost / Opportunity</div>
      <div class="diag-grid">
        <div class="diag-mini"><div class="k">Round-trip cost</div><div id="diagCost" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Cost hurdle</div><div id="diagHurdle" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Opportunity</div><div id="diagOpportunity" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Momentum</div><div id="diagMomentum" class="v">—</div></div>
      </div>
    </div>

    <div class="diag-section">
      <div class="diag-label">Cooldown / Position Management</div>
      <div class="diag-grid">
        <div class="diag-mini"><div class="k">Cooldown</div><div id="diagCooldown" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Until</div><div id="diagCooldownUntil" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Consecutive losses</div><div id="diagLosses" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Active stop</div><div id="diagStop" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Open P/L</div><div id="diagOpenPnl" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Today realized</div><div id="diagRealized" class="v">—</div></div>
        <div class="diag-mini"><div class="k">Entry avg</div><div id="diagEntry" class="v">—</div></div>
        <div class="diag-mini"><div class="k">High since entry</div><div id="diagHigh" class="v">—</div></div>
      </div>
    </div>

    <div id="diagFoot" class="diag-foot">Waiting for /api/v1/bot.</div>
  `;

  const grid=home.querySelector(".grid");
  if(grid){
    const perf=[...grid.children].find(el=>{
      const h=el.querySelector&&el.querySelector(".card-head h2");
      return h&&h.textContent.trim()==="PERFORMANCE SNAPSHOT";
    });
    if(perf) grid.insertBefore(card,perf);
    else grid.appendChild(card);
  }else{
    home.appendChild(card);
  }

  async function refresh(){
    try{
      const res=await fetch("/api/v1/bot",{cache:"no-store"});
      if(!res.ok) throw new Error("HTTP "+res.status);
      const b=await res.json();
      const m=b.strategy_metrics||{};

      text("diagStrategy",b.strategy);
      text("diagRegime",b.regime);
      text("diagReason",reasonLabel(b.strategy_reason));
      text("diagState",b.state);
      text("diagBars1",m.bars_1m??b.bars);
      text("diagBars5",m.bars_5m);
      text("diagBars15",m.bars_15m);
      text("diagEfficiency",num(m.efficiency));
      text("diag5m",(Number.isFinite(Number(m.fast_5m))?Number(m.fast_5m).toFixed(2):"—")+" / "+(Number.isFinite(Number(m.slow_5m))?Number(m.slow_5m).toFixed(2):"—"));
      text("diag15m",(Number.isFinite(Number(m.fast_15m))?Number(m.fast_15m).toFixed(2):"—")+" / "+(Number.isFinite(Number(m.slow_15m))?Number(m.slow_15m).toFixed(2):"—"));
      text("diagBreakout",m.breakout===true?"YES":m.breakout===false?"NO":"—");
      text("diagBreakoutLevel",moneySafe(m.breakout_level));
      text("diagCost",pct(b.round_trip_cost_pct??m.cost_pct));
      text("diagHurdle",pct(m.hurdle_pct));
      text("diagOpportunity",pct(m.opportunity_pct));
      text("diagMomentum",pct(m.momentum_pct));
      text("diagCooldown",b.cooldown_active?"ACTIVE":"CLEAR");
      text("diagCooldownUntil",b.cooldown_active?when(b.cooldown_until):"—");
      text("diagLosses",b.consecutive_losses??0);
      text("diagStop",moneySafe(b.position_stop));
      text("diagOpenPnl",moneySafe(b.open_pnl));
      text("diagRealized",moneySafe(b.daily_realized));
      text("diagEntry",moneySafe(b.avg_entry));
      text("diagHigh",moneySafe(b.highest_since_entry));

      tone(document.getElementById("diagOpenPnl"),b.open_pnl);
      tone(document.getElementById("diagRealized"),b.daily_realized);

      const badge=document.getElementById("diagRegimeBadge");
      if(badge){
        badge.className="pill "+regimeClass(b.regime);
        badge.textContent=String(b.regime||"UNKNOWN").toUpperCase();
      }
      const edge=Number(m.opportunity_pct), hurdle=Number(m.hurdle_pct);
      const edgeText=Number.isFinite(edge)&&Number.isFinite(hurdle)
        ? "EDGE "+edge.toFixed(3)+"% "+(edge>=hurdle?">=":"<")+" HURDLE "+hurdle.toFixed(3)+"%"
        : "EDGE/HURDLE WARMING";
      const strip=document.getElementById("strategyStrip");
      if(strip){
        strip.innerHTML="<strong>"+String(b.regime||"unknown").toUpperCase()+"</strong> · "+reasonLabel(b.strategy_reason)+" · "+edgeText+(b.cooldown_active?" · COOLDOWN":"");
      }
      text("diagFoot",
        "Mark source: "+String(b.mark_source||"—")+
        " · Bars: "+String(b.bars??0)+
        " · Tick age: "+String(b.last_tick_age_ms??"—")+" ms"+
        " · Paper mode: "+String(Boolean(b.paper_mode)).toUpperCase()
      );
    }catch(err){
      const foot=document.getElementById("diagFoot");
      if(foot) foot.textContent="Strategy diagnostics unavailable: "+err.message;
      const strip=document.getElementById("strategyStrip");
      if(strip) strip.innerHTML="<strong>STRATEGY</strong> · diagnostics unavailable";
    }
  }

  refresh();
  setInterval(refresh,5000);
})();