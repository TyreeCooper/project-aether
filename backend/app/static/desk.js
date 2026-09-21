(function(){
  const theme=localStorage.getItem("aether-theme")||"dark";
  document.documentElement.setAttribute("data-theme",theme);

  const bar=document.querySelector(".topbar");
  if(bar && !document.getElementById("menuBtn")){
    const btn=document.createElement("button");
    btn.id="menuBtn"; btn.className="menu-btn"; btn.type="button"; btn.setAttribute("aria-label","Menu");
    btn.innerHTML="<span></span><span></span><span></span>";
    bar.insertBefore(btn, bar.firstChild);
    const scrim=document.createElement("div"); scrim.className="scrim"; scrim.id="scrim";
    const drawer=document.createElement("nav"); drawer.className="drawer"; drawer.id="drawer";
    drawer.innerHTML='<div class="brand-title" style="margin-bottom:12px">AETHER</div><a href="#">Journal</a><a href="#">Charts</a><a href="#">Booth</a>';
    document.body.appendChild(scrim); document.body.appendChild(drawer);
    const close=()=>{drawer.classList.remove("open");scrim.classList.remove("open")};
    btn.onclick=()=>{drawer.classList.add("open");scrim.classList.add("open")};
    scrim.onclick=close;
  }

  if(!document.getElementById("ticker")){
    const tape=document.createElement("div");
    tape.id="ticker"; tape.className="ticker";
    tape.innerHTML="<b id=\"tickerText\">AETHER · paper desk · waiting on tape · </b>";
    const app=document.querySelector(".app")||document.body;
    const top=document.querySelector(".topbar");
    if(top&&top.parentNode) top.after(tape); else app.insertBefore(tape, app.firstChild);
  }

  const brandTitle=document.querySelector(".brand-title");
  const brandSub=document.querySelector(".brand-sub");
  if(brandTitle) brandTitle.textContent="AETHER";
  if(brandSub) brandSub.textContent="Paper desk";

  const titles={"page-home":["Floor","Kraken paper tape"],"page-trade":["Ticket","Place or flatten"],"page-activity":["Blotter","Fills as they print"],"page-analytics":["Book","Wins, losses, fees"],"page-settings":["Booth","Keys, risk, theme"]};
  Object.entries(titles).forEach(([id,pair])=>{
    const page=document.getElementById(id); if(!page) return;
    const h=page.querySelector(".page-head h1"); const p=page.querySelector(".page-head p");
    if(h) h.textContent=pair[0]; if(p) p.textContent=pair[1];
  });

  const inner=document.querySelector(".nav-inner");
  if(inner){
    const order=["trade","activity","home","analytics","settings"];
    const map={};
    inner.querySelectorAll(".nav-btn").forEach(b=>map[b.getAttribute("data-page")]=b);
    order.forEach(k=>{ if(map[k]) inner.appendChild(map[k]); });
    const labels={home:"Floor",trade:"Ticket",activity:"Blotter",analytics:"Book",settings:"Booth"};
    inner.querySelectorAll(".nav-btn").forEach(b=>{
      const s=b.querySelector("span"); if(s&&labels[b.getAttribute("data-page")]) s.textContent=labels[b.getAttribute("data-page")];
    });
  }

  const settings=document.getElementById("page-settings");
  if(settings && !document.getElementById("themeCard")){
    const card=document.createElement("section"); card.className="card full"; card.id="themeCard";
    card.innerHTML='<div class="card-head"><h2>LOOK</h2><span class="pill">THEME</span></div><div class="row"><span>Mode</span><span id="themeNow">'+theme+'</span></div><div class="action-grid" style="margin-top:8px"><button type="button" class="btn secondary" id="themeDark">Dark</button><button type="button" class="btn secondary" id="themeLight">Light</button></div>';
    settings.querySelector(".grid")?.appendChild(card);
    const setTheme=next=>{document.documentElement.setAttribute("data-theme",next);localStorage.setItem("aether-theme",next);const n=document.getElementById("themeNow"); if(n) n.textContent=next;};
    document.getElementById("themeDark")?.addEventListener("click",()=>setTheme("dark"));
    document.getElementById("themeLight")?.addEventListener("click",()=>setTheme("light"));
  }

  function mountSpark(host, id){
    if(!host || document.getElementById(id)) return document.getElementById(id);
    const wrap=document.createElement("div"); wrap.id=id; wrap.style.marginTop="8px"; host.appendChild(wrap); return wrap;
  }
  function drawSpark(el, values){
    if(!el) return;
    const w=200,h=64,pad=8;
    if(!values.length){el.innerHTML="";return;}
    const min=Math.min.apply(null,values), max=Math.max.apply(null,values), span=max-min||1;
    const pts=values.map((v,i)=>{
      const x=pad+i*((w-pad*2)/Math.max(values.length-1,1));
      const y=h-pad-((v-min)/span)*(h-pad*2);
      return [x,y,v];
    });
    const d="M"+pts.map(p=>p[0].toFixed(1)+","+p[1].toFixed(1)).join(" L");
    const last=pts[pts.length-1];
    el.innerHTML='<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><path d="'+d+'"/><circle class="dot" cx="'+last[0]+'" cy="'+last[1]+'" r="3.2"/><text class="fresh" id="'+el.id+'Val" x="8" y="12" fill="currentColor" font-size="9">'+last[2].toFixed(2)+'</text></svg>';
    const svg=el.querySelector("svg"); const dot=el.querySelector(".dot"); const lab=el.querySelector("text");
    const pick=ev=>{
      const r=svg.getBoundingClientRect();
      const x=((ev.touches?ev.touches[0].clientX:ev.clientX)-r.left)/r.width*w;
      let best=pts[0], dist=1e9;
      pts.forEach(p=>{const n=Math.abs(p[0]-x); if(n<dist){dist=n;best=p;}});
      dot.setAttribute("cx",best[0]); dot.setAttribute("cy",best[1]);
      if(lab) lab.textContent=best[2].toFixed(2);
    };
    svg.addEventListener("pointerdown",pick); svg.addEventListener("pointermove",e=>{ if(e.buttons||e.touches) pick(e); });
  }

  const stack=document.getElementById("eq")?.closest(".card");
  const stackSpark=mountSpark(stack,"stackSpark");
  const board=document.getElementById("scoreboard");
  const boardSpark=mountSpark(board,"boardSpark");

  async function refreshLive(){
    try{
      const [a,b,l]=await Promise.all([
        fetch("/api/v1/account").then(r=>r.json()),
        fetch("/api/v1/bot").then(r=>r.json()),
        fetch("/api/v1/learn").then(r=>r.json())
      ]);
      const live=l.live_exits||{};
      const t=document.getElementById("tickerText");
      if(t){
        const px=a.mark==null?"—":Number(a.mark).toFixed(0);
        const bid=a.bid==null?"—":Number(a.bid).toFixed(0);
        const ask=a.ask==null?"—":Number(a.ask).toFixed(0);
        const watch=a.watch_last==null?"—":Number(a.watch_last).toFixed(0);
        t.textContent="BTC-USD "+px+"  ·  bid "+bid+"  ·  ask "+ask+"  ·  watch "+watch+"  ·  "+ (b.state||"") +"  ·  paper  ·  ";
      }
      const series=(live.series||[]).map(x=>x.cum);
      drawSpark(stackSpark, series);
      drawSpark(boardSpark, series);
      const eqHist=await fetch("/api/v1/history/account?limit=40").then(r=>r.json()).catch(()=>({items:[]}));
      const eq=(eqHist.items||[]).map(x=>Number(x.equity)).filter(Number.isFinite).reverse();
      if(eq.length) drawSpark(stackSpark, eq);
    }catch(e){}
  }
  refreshLive(); setInterval(refreshLive, 5000);
})();
