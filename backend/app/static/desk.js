(function(){
  const theme=localStorage.getItem("aether-theme")||"dark";
  document.documentElement.setAttribute("data-theme",theme);
  const bar=document.querySelector(".topbar");
  if(bar && !document.getElementById("menuBtn")){
    const btn=document.createElement("button");
    btn.id="menuBtn";btn.className="menu-btn";btn.type="button";btn.innerHTML="<span></span><span></span><span></span>";
    bar.insertBefore(btn, bar.firstChild);
    const scrim=document.createElement("div");scrim.className="scrim";scrim.id="scrim";
    const drawer=document.createElement("nav");drawer.className="drawer";drawer.id="drawer";
    drawer.innerHTML="<a href=\"#\">Journal</a><a href=\"#\">Charts</a><a href=\"#\">Booth</a>";
    document.body.append(scrim,drawer);
    btn.onclick=()=>{drawer.classList.add("open");scrim.classList.add("open")};
    scrim.onclick=()=>{drawer.classList.remove("open");scrim.classList.remove("open")};
  }
  if(!document.getElementById("ticker")){
    const tape=document.createElement("div");tape.id="ticker";tape.className="ticker";
    tape.innerHTML="<b id=\"tickerText\">BTC-USD</b>";
    const top=document.querySelector(".topbar"); if(top) top.after(tape);
  }
  const board=document.getElementById("scoreboard");
  if(board && !document.getElementById("tvWrap")){
    const wrap=document.createElement("div"); wrap.id="tvWrap"; wrap.className="tv-wrap card full";
    wrap.innerHTML='<div id="tvKraken" style="height:280px"></div>';
    board.parentNode.insertBefore(wrap, board);
    const boot=()=>{
      if(!window.TradingView) return;
      const dark=document.documentElement.getAttribute("data-theme")!=="light";
      new window.TradingView.widget({autosize:true,symbol:"KRAKEN:XBTUSD",interval:"60",timezone:"Etc/UTC",theme:dark?"dark":"light",style:"1",locale:"en",container_id:"tvKraken",hide_legend:false,allow_symbol_change:false});
    };
    if(window.TradingView) boot();
    else {const s=document.createElement("script"); s.src="https://s3.tradingview.com/tv.js"; s.onload=boot; document.body.appendChild(s);}
  }
  const brandTitle=document.querySelector(".brand-title"); if(brandTitle) brandTitle.textContent="AETHER";
  const brandSub=document.querySelector(".brand-sub"); if(brandSub) brandSub.textContent="Paper desk";

  const inner=document.querySelector(".nav-inner");
  if(inner){
    const order=["trade","activity","home","analytics","settings"];
    const map={};
    inner.querySelectorAll(".nav-btn").forEach(b=>map[b.getAttribute("data-page")]=b);
    order.forEach(k=>{ if(map[k]) inner.appendChild(map[k]); });
    const labels={home:"Floor",trade:"Ticket",activity:"Blotter",analytics:"Book",settings:"Booth"};
    inner.querySelectorAll(".nav-btn").forEach(b=>{
      const s=b.querySelector("span");
      if(s && labels[b.getAttribute("data-page")]) s.textContent=labels[b.getAttribute("data-page")];
    });
    if(!inner.querySelector(".dock-slide")){
      const ghost=document.createElement("div"); ghost.className="dock-ghost";
      const slide=document.createElement("div"); slide.className="dock-slide";
      inner.insertBefore(ghost, inner.firstChild);
      inner.insertBefore(slide, inner.firstChild);
      const move=()=>{
        const on=inner.querySelector(".nav-btn.active")||map.home||inner.querySelector(".nav-btn");
        if(!on) return;
        const r=inner.getBoundingClientRect(), b=on.getBoundingClientRect();
        const left=(b.left-r.left)+"px";
        const width=b.width+"px";
        ghost.style.left=left; ghost.style.width=width;
        slide.style.left=left; slide.style.width=width;
      };
      inner.querySelectorAll(".nav-btn").forEach(b=>b.addEventListener("click",()=>setTimeout(move,30)));
      setTimeout(move,80);
      window.addEventListener("resize",move);
    }
  }

  const settings=document.getElementById("page-settings");
  if(settings && !document.getElementById("themeCard")){
    const card=document.createElement("section");card.className="card full";card.id="themeCard";
    card.innerHTML='<div class="card-head"><h2>LOOK</h2></div><div class="action-grid"><button class="btn secondary" id="themeDark" type="button">Dark</button><button class="btn secondary" id="themeLight" type="button">Light</button></div>';
    settings.querySelector(".grid")?.appendChild(card);
    const set=t=>{document.documentElement.setAttribute("data-theme",t);localStorage.setItem("aether-theme",t); location.reload();};
    document.getElementById("themeDark")?.addEventListener("click",()=>set("dark"));
    document.getElementById("themeLight")?.addEventListener("click",()=>set("light"));
  }
  function fmt(n){
    const v=Number(n);
    if(!Number.isFinite(v)) return "\u2014";
    return v.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:8});
  }
  function chart(el, values){
    if(!el) return;
    el.classList.add("chart-shell");
    const w=280,h=108,p=16;
    if(!values.length){el.innerHTML="";return;}
    const min=Math.min.apply(null,values), max=Math.max.apply(null,values), span=max-min||1;
    const pts=values.map((v,i)=>({x:p+i*((w-p*2)/Math.max(values.length-1,1)), y:h-p-((v-min)/span)*(h-p*2), v}));
    const d=pts.map((pt,i)=>(i?"L":"M")+pt.x.toFixed(1)+","+pt.y.toFixed(1)).join(" ");
    const last=pts[pts.length-1];
    const area=d+" L"+last.x.toFixed(1)+","+(h-p)+" L"+pts[0].x.toFixed(1)+","+(h-p)+" Z";
    let grid="";
    for(let i=0;i<5;i++){const y=p+i*((h-p*2)/4); grid+='<line class="grid" x1="'+p+'" x2="'+(w-p)+'" y1="'+y+'" y2="'+y+'" />';}
    for(let i=0;i<6;i++){const x=p+i*((w-p*2)/5); grid+='<line class="grid" y1="'+p+'" y2="'+(h-p)+'" x1="'+x+'" x2="'+x+'" />';}
    el.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><defs><linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#26a69a"/><stop offset="1" stop-color="#26a69a" stop-opacity="0"/></linearGradient></defs>'+grid+'<path class="area" d="'+area+'"/><path class="line" d="'+d+'"/><circle class="dot" cx="'+last.x+'" cy="'+last.y+'" r="2.4"/><text class="read" x="8" y="12">'+fmt(last.v)+'</text></svg>';
    const svg=el.querySelector("svg"), dot=el.querySelector(".dot"), lab=el.querySelector("text");
    const pick=ev=>{
      const r=svg.getBoundingClientRect();
      const x=((ev.touches?ev.touches[0].clientX:ev.clientX)-r.left)/r.width*w;
      let best=pts[0], dist=1e9; pts.forEach(pt=>{const n=Math.abs(pt.x-x); if(n<dist){dist=n;best=pt;}});
      dot.setAttribute("cx",best.x); dot.setAttribute("cy",best.y); lab.textContent=fmt(best.v);
    };
    svg.onpointerdown=pick; svg.onpointermove=e=>{if(e.buttons) pick(e);};
  }
  function mount(id, host){
    let el=document.getElementById(id); if(el) return el; if(!host) return null;
    el=document.createElement("div"); el.id=id; host.appendChild(el); return el;
  }
  async function tick(){
    try{
      const [a,l,h]=await Promise.all([
        fetch("/api/v1/account").then(r=>r.json()),
        fetch("/api/v1/learn").then(r=>r.json()),
        fetch("/api/v1/history/account?limit=48").then(r=>r.json()).catch(()=>({items:[]}))
      ]);
      const k=Number(a.mark), w=Number(a.watch_last||a.mark);
      const cell=(sym,px)=>{const up=px>=k*0.999; return '<span class="sym">'+sym+' '+fmt(px)+' <span class="'+(up?"up":"dn")+'">'+(up?"\u25b2":"\u25bc")+'</span></span> ';};
      const t=document.getElementById("tickerText");
      if(t && Number.isFinite(k)) t.innerHTML=[cell("BTC-USD",k),cell("BTCUSD",k),cell("XBTUSD",k),cell("BTC/USD",k),cell("BTCUSDT",Number.isFinite(w)?w:k)].join("   ");
      const eq=(h.items||[]).map(x=>Number(x.equity)).filter(Number.isFinite).reverse();
      const pnl=(l.live_exits&&l.live_exits.series||[]).map(x=>x.cum);
      chart(mount("stackChart", document.getElementById("eq")?.closest(".card")), eq.length?eq:pnl);
      chart(mount("boardChart", document.getElementById("scoreboard")), pnl.length?pnl:eq);
      chart(mount("spanChart", document.getElementById("periodCard")), pnl);
      chart(mount("journalChart", document.getElementById("learnCard")), pnl);
    }catch(e){}
  }
  tick(); setInterval(tick, 5000);
})();
