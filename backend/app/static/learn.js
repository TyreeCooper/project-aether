(function(){
  const host=document.getElementById("page-home");
  if(!host||document.getElementById("learnCard")) return;
  const card=document.createElement("section");
  card.className="card full"; card.id="learnCard"; card.style.marginTop="10px";
  card.innerHTML='<div class="card-head"><h2>JOURNAL</h2><span id="lnFresh" class="fresh">auto</span></div>'+
    '<div class="row"><span>Rule</span><span id="lnChamp">8 / 21 stop</span></div>'+
    '<div class="row"><span>Note</span><span id="lnLive">—</span></div>'+
    '<div class="row"><span>Per trade</span><span id="lnExp">—</span></div>'+
    '<div id="lnSpark"></div>'+
    '<div id="lnNote" class="helper">Writes itself after exits. Does not flip the book.</div>';
  const grid=host.querySelector(".grid");
  if(grid) host.insertBefore(card, grid.nextSibling); else host.appendChild(card);
  function spark(el, values){
    if(!el) return;
    const w=160,h=48,pad=3;
    if(!values.length){el.innerHTML="";return;}
    const min=Math.min.apply(null,values), max=Math.max.apply(null,values), span=max-min||1;
    const pts=values.map((v,i)=>{
      const x=pad+i*((w-pad*2)/Math.max(values.length-1,1));
      const y=h-pad-((v-min)/span)*(h-pad*2);
      return x.toFixed(1)+","+y.toFixed(1);
    });
    el.innerHTML='<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><path d="M'+pts.join(" L")+'"/></svg>';
  }
  function paint(d){
    const c=d.champion||{}, live=d.live_exits||{};
    document.getElementById("lnChamp").textContent=(c.short_ma||8)+" / "+(c.long_ma||21)+" stop";
    document.getElementById("lnLive").textContent=(live.wins||0)+" up · "+(live.losses||0)+" down";
    document.getElementById("lnExp").textContent=live.expectancy_usd==null?"—":"$"+Number(live.expectancy_usd).toFixed(2);
    const age=live.last_exit_age_s;
    document.getElementById("lnFresh").textContent=age==null?"no exit yet":(age<60?age+"s old":Math.floor(age/60)+"m old");
    spark(document.getElementById("lnSpark"), (live.series||[]).map(x=>x.cum));
    document.getElementById("lnNote").textContent=d.note||"Watching closes.";
  }
  async function loadLearn(){
    try{ paint(await fetch("/api/v1/learn").then(r=>r.json())); }
    catch(e){ document.getElementById("lnNote").textContent="Journal offline."; }
  }
  loadLearn(); setInterval(loadLearn, 30000);
})();
