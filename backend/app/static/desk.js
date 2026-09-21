(function(){
  const theme=localStorage.getItem("aether-theme")||"dark";
  document.documentElement.setAttribute("data-theme",theme);

  const bar=document.querySelector(".topbar");
  if(bar && !document.getElementById("menuBtn")){
    const btn=document.createElement("button");
    btn.id="menuBtn";btn.className="menu-btn";btn.type="button";btn.setAttribute("aria-label","Menu");
    btn.innerHTML="<span></span><span></span><span></span>";
    bar.insertBefore(btn, bar.firstChild);
    const scrim=document.createElement("div");scrim.className="scrim";scrim.id="scrim";
    const drawer=document.createElement("nav");drawer.className="drawer";drawer.id="drawer";
    drawer.innerHTML='<div class="brand-title" style="margin-bottom:12px">AETHER</div><a href="#">Journal</a><a href="#">Charts</a><a href="#">Booth</a>';
    document.body.appendChild(scrim);document.body.appendChild(drawer);
    function close(){drawer.classList.remove("open");scrim.classList.remove("open")}
    btn.onclick=()=>{drawer.classList.add("open");scrim.classList.add("open")};
    scrim.onclick=close;
  }

  const brandTitle=document.querySelector(".brand-title");
  const brandSub=document.querySelector(".brand-sub");
  if(brandTitle) brandTitle.textContent="AETHER";
  if(brandSub) brandSub.textContent="Paper desk";

  const titles={ "page-home":["Floor","Kraken paper tape"],"page-trade":["Ticket","Place or flatten"],"page-activity":["Blotter","Fills as they print"],"page-analytics":["Book","Wins, losses, fees"],"page-settings":["Booth","Keys, risk, theme"]};
  Object.entries(titles).forEach(([id,pair])=>{
    const page=document.getElementById(id); if(!page) return;
    const h=page.querySelector(".page-head h1"); const p=page.querySelector(".page-head p");
    if(h) h.textContent=pair[0]; if(p) p.textContent=pair[1];
  });
  const dock={home:"Floor",trade:"Ticket",activity:"Blotter",analytics:"Book",settings:"Booth"};
  document.querySelectorAll(".nav-btn").forEach(btn=>{
    const key=btn.getAttribute("data-page");
    const label=btn.querySelector("span");
    if(dock[key]&&label) label.textContent=dock[key];
  });

  const settings=document.getElementById("page-settings");
  if(settings && !document.getElementById("themeCard")){
    const card=document.createElement("section");
    card.className="card full"; card.id="themeCard";
    card.innerHTML='<div class="card-head"><h2>LOOK</h2><span class="pill">THEME</span></div><div class="row"><span>Mode</span><span id="themeNow">'+theme+'</span></div><div class="action-grid" style="margin-top:8px"><button type="button" class="btn secondary" id="themeDark">Dark</button><button type="button" class="btn secondary" id="themeLight">Light</button></div>';
    settings.querySelector(".grid")?.appendChild(card);
    const setTheme=next=>{document.documentElement.setAttribute("data-theme",next);localStorage.setItem("aether-theme",next);const n=document.getElementById("themeNow"); if(n) n.textContent=next;};
    document.getElementById("themeDark")?.addEventListener("click",()=>setTheme("dark"));
    document.getElementById("themeLight")?.addEventListener("click",()=>setTheme("light"));
  }

  function spark(el, values){
    if(!el) return;
    const w=160,h=56,pad=4;
    if(!values.length){el.innerHTML='';return;}
    const min=Math.min.apply(null,values), max=Math.max.apply(null,values);
    const span=max-min||1;
    const pts=values.map((v,i)=>{
      const x=pad+i*((w-pad*2)/Math.max(values.length-1,1));
      const y=h-pad-((v-min)/span)*(h-pad*2);
      return x.toFixed(1)+","+y.toFixed(1);
    });
    el.innerHTML='<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><path d="M'+pts.join(" L")+'"/></svg>';
  }
  function ageLabel(iso, seconds){
    if(seconds==null && !iso) return "No print yet";
    if(seconds!=null){
      if(seconds<60) return seconds+"s old";
      if(seconds<3600) return Math.floor(seconds/60)+"m old";
      return Math.floor(seconds/3600)+"h old";
    }
    return "as of "+iso.slice(11,16)+"Z";
  }
  function usd(n){ const v=Number(n); if(!Number.isFinite(v)) return "—"; return (v<0?"-$":"$")+Math.abs(v).toFixed(2); }

  const home=document.getElementById("page-home");
  if(home && !document.getElementById("periodCard")){
    const card=document.createElement("section");
    card.className="card full"; card.id="periodCard";
    card.innerHTML='<div class="card-head"><h2>SPAN</h2><span id="spanFresh" class="fresh">checking</span></div>'+
      '<div class="summary"><div class="box"><div class="k">Week</div><div id="spanWeek" class="v">—</div></div><div class="box"><div class="k">Month</div><div id="spanMonth" class="v">—</div></div><div class="box"><div class="k">Year</div><div id="spanYear" class="v">—</div></div><div class="box"><div class="k">Flip</div><div id="spanFlip" class="v">—</div></div></div><div id="spanSpark"></div><div id="spanHint" class="hint">Flip is the opposite-side book. Not a live short.</div>';
    home.querySelector(".grid")?.appendChild(card);
  }
  async function paintSpan(){
    try{
      const d=await fetch("/api/v1/learn").then(r=>r.json());
      const live=d.live_exits||{};
      const set=(id,v)=>{const el=document.getElementById(id); if(el) el.textContent=usd(v);};
      set("spanWeek", live.weekly_pnl_usd);
      set("spanMonth", live.monthly_pnl_usd);
      set("spanYear", live.annual_pnl_usd);
      set("spanFlip", live.invert_pnl_usd);
      const fresh=document.getElementById("spanFresh");
      if(fresh) fresh.textContent=ageLabel(live.last_exit_at, live.last_exit_age_s);
      spark(document.getElementById("spanSpark"), (live.series||[]).map(x=>x.cum));
      const hint=document.getElementById("spanHint");
      if(hint && live.closed && Number(live.invert_pnl_usd)>Number(live.realized_pnl_usd)){
        hint.textContent="Opposite side won this sample. Long-only stays on.";
      }
    }catch(e){}
  }
  paintSpan(); setInterval(paintSpan, 20000);

  const mark=document.getElementById("mark");
  if(mark && !document.getElementById("tapeFresh")){
    const stamp=document.createElement("div");
    stamp.id="tapeFresh"; stamp.className="fresh"; stamp.textContent="tape age —";
    mark.after(stamp);
  }
  async function tapeAge(){
    try{
      const b=await fetch("/api/v1/bot").then(r=>r.json());
      const el=document.getElementById("tapeFresh");
      if(!el) return;
      const ms=b.last_tick_age_ms;
      el.textContent=ms==null?"no tick":(Math.round(ms/1000)+"s old");
    }catch(e){}
  }
  tapeAge(); setInterval(tapeAge, 5000);
})();
