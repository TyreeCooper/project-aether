(function(){
  const host=document.getElementById("page-home");
  if(!host||document.getElementById("learnCard")) return;
  const card=document.createElement("section");
  card.className="card full";
  card.id="learnCard";
  card.style.marginTop="10px";
  card.innerHTML='<div class="card-head"><h2>JOURNAL</h2><span class="pill">AUTO</span></div>'+
    '<div class="row"><span>Rule</span><span id="lnChamp">8 / 21 stop</span></div>'+
    '<div class="row"><span>Note</span><span id="lnLive">—</span></div>'+
    '<div class="row"><span>Per trade</span><span id="lnExp">—</span></div>'+
    '<div id="lnNote" class="helper">Writes itself after exits. Does not change the rule.</div>';
  const grid=host.querySelector(".grid");
  if(grid) host.insertBefore(card, grid.nextSibling);
  else host.appendChild(card);

  function paint(d){
    const c=d.champion||{};
    document.getElementById("lnChamp").textContent=(c.short_ma||8)+" / "+(c.long_ma||21)+" stop";
    const live=d.live_exits||{};
    document.getElementById("lnLive").textContent=(live.wins||0)+" up · "+(live.losses||0)+" down";
    document.getElementById("lnExp").textContent=live.expectancy_usd==null?"—":"$"+Number(live.expectancy_usd).toFixed(2);
    const hist=(d.history||[])[0];
    document.getElementById("lnNote").textContent=d.promote_ready
      ? "Better nearby rule found. Still waiting."
      : (hist ? "Last pass quiet." : "Watching closes.");
  }
  async function loadLearn(){
    try{ paint(await fetch("/api/v1/learn").then(r=>r.json())); }
    catch(e){ document.getElementById("lnNote").textContent="Journal offline."; }
  }
  loadLearn();
  setInterval(loadLearn, 30000);
})();
