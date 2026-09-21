(function(){
  const KEY="aether-asset";
  let assets=[];
  let selected=localStorage.getItem(KEY)||"btc";
  let sparks={};

  function money(n){
    const v=Number(n);
    if(!Number.isFinite(v)) return "\u2014";
    const d=v>=1000?2:v>=1?4:6;
    return v.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:d});
  }
  function current(){ return assets.find(a=>a.id===selected)||assets[0]; }
  function dark(){ return document.documentElement.getAttribute("data-theme")!=="light"; }

  function lineChart(el, values, up){
    if(!el) return;
    el.classList.add("spark");
    if(!values || values.length<2){ el.innerHTML=""; return; }
    const w=320,h=120,p=16;
    const min=Math.min.apply(null,values), max=Math.max.apply(null,values), span=max-min||1;
    const pts=values.map((v,i)=>({x:p+i*((w-p*2)/Math.max(values.length-1,1)), y:h-p-((v-min)/span)*(h-p*2), v}));
    const d=pts.map((pt,i)=>(i?"L":"M")+pt.x.toFixed(1)+","+pt.y.toFixed(1)).join(" ");
    const last=pts[pts.length-1];
    const gid="g"+el.id+values.length;
    const stroke=up?"#26a69a":"#ef5350";
    const grid=dark()?"rgba(255,255,255,.08)":"rgba(42,36,28,.14)";
    const ink=dark()?"#d1d4dc":"#2a241c";
    let gridLines="";
    for(let i=0;i<5;i++){const y=p+i*((h-p*2)/4); gridLines+='<line stroke="'+grid+'" x1="'+p+'" x2="'+(w-p)+'" y1="'+y+'" y2="'+y+'"/>';}
    el.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+stroke+'" stop-opacity=".35"/><stop offset="1" stop-color="'+stroke+'" stop-opacity="0"/></linearGradient></defs>'+gridLines+'<path fill="url(#'+gid+')" d="'+d+' L'+last.x+','+(h-p)+' L'+pts[0].x+','+(h-p)+' Z"/><path fill="none" stroke="'+stroke+'" stroke-width="1.4" d="'+d+'"/><circle class="dot" fill="#f3a437" cx="'+last.x+'" cy="'+last.y+'" r="3"/><text fill="'+ink+'" font-size="10" font-weight="600" x="8" y="12">'+money(last.v)+'</text></svg>';
    const svg=el.querySelector("svg"), dot=el.querySelector(".dot"), lab=el.querySelector("text");
    const pick=ev=>{
      const r=svg.getBoundingClientRect();
      const x=((ev.touches?ev.touches[0].clientX:ev.clientX)-r.left)/r.width*w;
      let best=pts[0], dist=1e9; pts.forEach(pt=>{const n=Math.abs(pt.x-x); if(n<dist){dist=n;best=pt;}});
      dot.setAttribute("cx",best.x); dot.setAttribute("cy",best.y); lab.textContent=money(best.v);
    };
    svg.onpointerdown=pick; svg.onpointermove=e=>{if(e.buttons) pick(e);};
  }

  function ensureShell(){
    if(!document.getElementById("deskMarketsCss")){
      const l=document.createElement("link"); l.id="deskMarketsCss"; l.rel="stylesheet"; l.href="/static/desk-markets.css"; document.head.appendChild(l);
    }
    if(!document.getElementById("assetRail")){
      const rail=document.createElement("div"); rail.id="assetRail"; rail.className="asset-rail";
      const tape=document.getElementById("ticker");
      if(tape) tape.after(rail); else document.querySelector(".topbar")?.after(rail);
    }
    if(!document.getElementById("deskBoard")){
      const board=document.createElement("section");
      board.id="deskBoard"; board.className="card full";
      board.innerHTML='<div class="card-head"><h2>DESK</h2><p class="muted">Master book</p></div><div id="deskTotals" class="desk-totals"></div><div id="deskList" class="desk-list"></div>';
      const home=document.getElementById("page-home");
      const hero=home?.querySelector(".market-hero");
      if(hero) hero.after(board); else home?.prepend(board);
    }
    if(!document.getElementById("assetProfile")){
      const card=document.createElement("section");
      card.id="assetProfile"; card.className="card full asset-profile";
      card.innerHTML='<div class="asset-card-top"><div><p class="symbol-title" id="assetPair">BTC/USD</p><p class="asset-name" id="assetName">Bitcoin</p></div><span class="asset-chip" id="assetMode">PAPER</span></div><div class="price" id="assetLast">\u2014</div><div class="asset-quote"><span>Kraken bid <b id="assetBid">\u2014</b></span><span>Kraken ask <b id="assetAsk">\u2014</b></span></div><div class="asset-quote"><span>Binance last <b id="assetWatch">\u2014</b></span><span>Basis <b id="assetBasis">\u2014</b></span></div><div id="assetSpark" class="spark"></div>';
      document.getElementById("deskBoard")?.after(card);
    }
  }

  function paintTape(){
    const t=document.getElementById("tickerText");
    if(!t || !assets.length) return;
    t.innerHTML=assets.map(a=>{
      const up=Number(a.watch_last||a.last)>=Number(a.last||0)*0.999;
      return '<span class="sym">'+a.pair+' '+money(a.last)+' <span class="'+(up?"up":"dn")+'">'+(up?"\u25b2":"\u25bc")+'</span></span>';
    }).join("   ");
  }

  function paintRail(){
    const rail=document.getElementById("assetRail"); if(!rail) return;
    rail.innerHTML=assets.map(a=>{
      const on=a.id===selected?" on":"";
      return '<button type="button" class="asset-pill'+on+'" data-id="'+a.id+'">'+a.symbol+'<em>'+money(a.last)+'</em></button>';
    }).join("");
    rail.querySelectorAll(".asset-pill").forEach(btn=>btn.onclick=()=>select(btn.getAttribute("data-id")));
  }

  function paintBoard(){
    const list=document.getElementById("deskList");
    const totals=document.getElementById("deskTotals");
    if(!list) return;
    list.innerHTML=assets.map(a=>{
      return '<button type="button" class="desk-row" data-id="'+a.id+'"><b>'+a.pair+'</b><span>'+money(a.last)+'</span><i class="'+(a.paper?"up":"dn")+'">'+(a.paper?"PAPER":"WATCH")+'</i></button>';
    }).join("");
    list.querySelectorAll(".desk-row").forEach(b=>b.onclick=()=>select(b.getAttribute("data-id")));
    if(totals){
      const n=assets.filter(a=>a.last!=null).length;
      totals.innerHTML='<span>'+n+' live pairs</span><span>Fill book BTC/USD</span><span>Watch Binance.US</span>';
    }
  }

  function paintProfile(){
    const a=current(); if(!a) return;
    const set=(id,v)=>{const el=document.getElementById(id); if(el) el.textContent=v;};
    set("assetPair", a.pair);
    set("assetName", a.name);
    set("assetLast", "$"+money(a.last));
    set("assetBid", money(a.bid));
    set("assetAsk", money(a.ask));
    set("assetWatch", money(a.watch_last));
    const basis=(a.watch_last!=null && a.last!=null)?(a.watch_last-a.last):null;
    set("assetBasis", basis==null?"\u2014":money(basis));
    const mode=document.getElementById("assetMode");
    if(mode) mode.textContent=a.paper?"PAPER FILL":"WATCH";
    const series=sparks[a.id]||[];
    const up=series.length>1?series[series.length-1]>=series[0]:true;
    lineChart(document.getElementById("assetSpark"), series, up);
  }

  function bootTv(symbol){
    const host=document.getElementById("tvKraken");
    if(!host || !window.TradingView) return;
    host.innerHTML="";
    new window.TradingView.widget({
      autosize:true, symbol:symbol, interval:"60", timezone:"Etc/UTC",
      theme:dark()?"dark":"light", style:"1", locale:"en",
      container_id:"tvKraken", hide_legend:false, allow_symbol_change:false
    });
  }

  function select(id){
    selected=id; localStorage.setItem(KEY,id);
    paintRail(); paintBoard(); paintProfile();
    const a=current(); if(a && a.tv) bootTv(a.tv);
    loadSpark(id);
  }

  async function loadSpark(id){
    try{
      const res=await fetch("/api/v1/markets/"+id);
      if(!res.ok) return;
      const data=await res.json();
      const closes=(data.closes||[]).map(Number).filter(Number.isFinite);
      if(closes.length) sparks[id]=closes;
      if(selected===id) paintProfile();
    }catch(e){}
  }

  async function load(){
    ensureShell();
    try{
      const res=await fetch("/api/v1/markets");
      const data=await res.json();
      assets=data.items||[];
      assets.forEach(a=>{
        if(a.last==null) return;
        sparks[a.id]=sparks[a.id]||[];
        sparks[a.id].push(Number(a.last));
        if(sparks[a.id].length>48) sparks[a.id].shift();
      });
      if(!assets.some(a=>a.id===selected)) selected="btc";
      paintTape(); paintRail(); paintBoard(); paintProfile();
    }catch(e){}
  }

  load();
  loadSpark(selected);
  setInterval(load, 8000);
})();
