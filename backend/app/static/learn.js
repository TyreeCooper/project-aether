(function(){
  const host=document.getElementById("page-home");
  if(!host||document.getElementById("learnCard")) return;
  const card=document.createElement("section");
  card.className="card full";
  card.id="learnCard";
  card.style.marginTop="10px";
  card.innerHTML='<div class="card-head"><h2>LEARNING</h2><span class="pill">CHAMPION / CHALLENGER</span></div>'+
    '<div class="row"><span>Champion</span><span id="lnChamp">8 / 21 / 2%</span></div>'+
    '<div class="row"><span>Challenger</span><span id="lnChall">none</span></div>'+
    '<div class="row"><span>Live exits</span><span id="lnLive">—</span></div>'+
    '<div class="row"><span>Expectancy</span><span id="lnExp">—</span></div>'+
    '<div class="row"><span>Exit mix</span><span id="lnMix">—</span></div>'+
    '<div id="lnNote" class="helper">Review scores nearby SMA settings on held Kraken bars. Promotion is manual.</div>'+
    '<button id="lnReview" class="btn secondary" type="button" style="margin-top:10px;min-height:34px">Run review</button>';
  const grid=host.querySelector(".grid");
  if(grid) host.insertBefore(card, grid.nextSibling);
  else host.appendChild(card);

  function paint(d){
    const c=d.champion||{};
    document.getElementById("lnChamp").textContent=(c.short_ma||8)+" / "+(c.long_ma||21)+" / "+(c.stop_loss_pct||2)+"%";
    document.getElementById("lnChall").textContent=d.challenger? (d.challenger.short_ma+" / "+d.challenger.long_ma+" / "+d.challenger.stop_loss_pct+"%") : "none";
    const live=d.live_exits||{};
    document.getElementById("lnLive").textContent=(live.wins||0)+"W / "+(live.losses||0)+"L / "+(live.breakeven||0)+"F";
    document.getElementById("lnExp").textContent=live.expectancy_usd==null?"—":"$"+Number(live.expectancy_usd).toFixed(2);
    const mix=live.exits_by_actor||{};
    document.getElementById("lnMix").textContent=Object.keys(mix).length?Object.entries(mix).map(([k,v])=>k+": "+v).join(" · "):"no exits";
    document.getElementById("lnNote").textContent=d.promote_ready?"Challenger beat champion on held bars. Promote only when OFFLINE and flat.":(d.note||"No challenger this review.");
  }
  async function loadLearn(){
    try{
      const d=await fetch("/api/v1/learn").then(r=>r.json());
      paint(d);
    }catch(e){
      document.getElementById("lnNote").textContent="Learning API unavailable.";
    }
  }
  document.getElementById("lnReview").addEventListener("click", async function(){
    this.disabled=true; this.textContent="Reviewing…";
    try{
      const d=await fetch("/api/v1/learn/review",{method:"POST"}).then(r=>r.json());
      paint(d);
    }catch(e){
      document.getElementById("lnNote").textContent="Review failed.";
    }
    this.disabled=false; this.textContent="Run review";
  });
  loadLearn();
})();
