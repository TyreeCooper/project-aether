(function(){
  const host=document.getElementById("page-home");
  if(!host||document.getElementById("scoreboard")) return;
  const box=document.createElement("section");
  box.className="card full";
  box.id="scoreboard";
  box.style.marginTop="10px";
  box.innerHTML='<div class="card-head"><h2>SCOREBOARD</h2><span class="pill">PAPER EXITS</span></div>'+
    '<div class="summary">'+
    '<div class="box"><div class="k">Wins</div><div id="sbWins" class="v" style="color:#28c77b">—</div></div>'+
    '<div class="box"><div class="k">Losses</div><div id="sbLosses" class="v" style="color:#ff5f6d">—</div></div>'+
    '<div class="box"><div class="k">Breakeven</div><div id="sbFlat" class="v">—</div></div>'+
    '<div class="box"><div class="k">Win rate</div><div id="sbRate" class="v">—</div></div>'+
    '<div class="box"><div class="k">Closed</div><div id="sbClosed" class="v">—</div></div>'+
    '<div class="box"><div class="k">Fees</div><div id="sbFees" class="v">—</div></div>'+
    '<div class="box"><div class="k">Today</div><div id="sbToday" class="v">—</div></div>'+
    '<div class="box"><div class="k">Week</div><div id="sbWeek" class="v">—</div></div>'+
    '</div><div id="sbLast" class="helper">Waiting for closed paper exits.</div>';
  const grid=host.querySelector(".grid");
  if(grid) host.insertBefore(box, grid);
  else host.appendChild(box);

  function tone(el, n){
    if(!el) return;
    const v=Number(n);
    el.style.color=!Number.isFinite(v)||Math.abs(v)<1e-9?"#f5f3fb":(v>0?"#28c77b":"#ff5f6d");
  }
  function usd(n){
    if(typeof money==="function") return money(n);
    const v=Number(n); if(!Number.isFinite(v)) return "—";
    return (v<0?"-$":"$")+Math.abs(v).toFixed(2);
  }
  async function refresh(){
    try{
      const [an, fills]=await Promise.all([
        fetch("/api/v1/analytics?limit=500").then(r=>r.json()),
        fetch("/api/v1/history/fills?limit=8").then(r=>r.json())
      ]);
      const wins=an.wins||0, losses=an.losses||0, flat=an.breakeven||0;
      document.getElementById("sbWins").textContent=String(wins);
      document.getElementById("sbLosses").textContent=String(losses);
      document.getElementById("sbFlat").textContent=String(flat);
      document.getElementById("sbRate").textContent=((an.win_rate_pct||0).toFixed?an.win_rate_pct.toFixed(1):an.win_rate_pct)+"%";
      document.getElementById("sbClosed").textContent=String(an.closed_exits||wins+losses+flat);
      document.getElementById("sbFees").textContent=usd(an.fees_usd);
      document.getElementById("sbToday").textContent=usd(an.daily_realized_pnl_usd);
      document.getElementById("sbWeek").textContent=usd(an.weekly_realized_pnl_usd);
      tone(document.getElementById("sbToday"), an.daily_realized_pnl_usd);
      tone(document.getElementById("sbWeek"), an.weekly_realized_pnl_usd);
      const exits=(fills.items||[]).filter(x=>String(x.side).toLowerCase()==="sell").slice(0,5);
      document.getElementById("sbLast").textContent=exits.length
        ? exits.map(x=>{
            const pnl=Number(x.realized_pnl_usd||0);
            const tag=Math.abs(pnl)<1e-9?"FLAT":(pnl>0?"WIN":"LOSS");
            return tag+" "+usd(pnl)+" @ "+usd(x.price_usd);
          }).join("   ·   ")
        : "No closed paper exits yet.";
    }catch(e){
      document.getElementById("sbLast").textContent="Scoreboard unavailable.";
    }
  }
  refresh();
  setInterval(refresh, 15000);
})();
