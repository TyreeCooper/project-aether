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
    tape.innerHTML="<b id=\"tickerText\">BTC · waiting · </b>";
    const top=document.querySelector(".topbar"); if(top) top.after(tape);
  }
  const brandTitle=document.querySelector(".brand-title");
  const brandSub=document.querySelector(".brand-sub");
  if(brandTitle) brandTitle.textContent="AETHER";
  if(brandSub) brandSub.textContent="Paper desk";

  const inner=document.querySelector(".nav-inner");
  if(inner){
    const order=["trade","activity","home","analytics","settings"];
    const map={};
    inner.querySelectorAll(".nav-btn").forEach(b=>map[b.getAttribute("data-page")]=b);
    order.forEach(k=>{if(map[k]) inner.appendChild(map[k]);});
    const labels={home:"Floor",trade:"Ticket",activity:"Blotter",analytics:"Book",settings:"Booth"};
    inner.querySelectorAll(".nav-btn").forEach(b=>{const s=b.querySelector("span"); if(s&&labels[b.getAttribute("data-page")]) s.textContent=labels[b.getAttribute("data-page")];});
    if(!inner.querySelector(".dock-slide")){
      const slide=document.createElement("div");slide.className="dock-slide";inner.insertBefore(slide, inner.firstChild);
      const move=()=>{
        const on=inner.querySelector(".nav-btn.active")||inner.querySelector('[data-page="home"]');
        if(!on) return;
        const r=inner.getBoundingClientRect(), b=on.getBoundingClientRect();
        slide.style.left=(b.left-r.left-4)+"px"; slide.style.width=(b.width+8)+"px";
      };
      inner.querySelectorAll(".nav-btn").forEach(b=>b.addEventListener("click",()=>setTimeout(move,20)));
      setTimeout(move,50); window.addEventListener("resize",move);
    }
  }

  const settings=document.getElementById("page-settings");
  if(settings && !document.getElementById("themeCard")){
    const card=document.createElement("section");card.className="card full";card.id="themeCard";
    card.innerHTML='<div class="card-head"><h2>LOOK</h2></div><div class="action-grid"><button class="btn secondary" id="themeDark" type="button">Dark</button><button class="btn secondary" id="themeLight" type="button">Light</button></div>';
    settings.querySelector(".grid")?.appendChild(card);
    const set=t=>{document.documentElement.setAttribute("data-theme",t);localStorage.setItem("aether-theme",t);};
    document.getElementById("themeDark")?.addEventListener("click",()=>set("dark"));
    document.getElementById("themeLight")?.addEventListener("click",()=>set("light"));
  }

  function chart(el, values){
    if(!el) return;
    el.classList.add("chart-shell");
    const w=240,h=88,p=10;
    if(!values.length){el.innerHTML="";return;}
    const min=Math.min.apply(null,values), max=Math.max.apply(null,values), span=max-min||1;
    const pts=values.map((v,i)=>{
      const x=p+i*((w-p*2)/Math.max(values.length-1,1));
      const y=h-p-((v-min)/span)*(h-p*2);
      return {x,y,v};
    });
    const d=pts.map((pt,i)=>(i?"L":"M")+pt.x.toFixed(1)+","+pt.y.toFixed(1)).join(" ");
    const last=pts[pts.length-1];
    const area=d+" L"+last.x.toFixed(1)+","+(h-p)+" L"+pts[0].x.toFixed(1)+","+(h-p)+" Z";
    el.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><defs><linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7b61ff"/><stop offset="1" stop-color="#7b61ff" stop-opacity="0"/></linearGradient></defs><path class="area" d="'+area+'"/><path class="line" d="'+d+'"/><circle class="dot" cx="'+last.x+'" cy="'+last.y+'" r="3"/><text class="read" x="8" y="12">'+last.v.toFixed(2)+'</text></svg>';
    const svg=el.querySelector("svg"), dot=el.querySelector(".dot"), lab=el.querySelector("text");
    const pick=ev=>{
      const r=svg.getBoundingClientRect();
      const x=((ev.touches?ev.touches[0].clientX:ev.clientX)-r.left)/r.width*w;
      let best=pts[0], dist=1e9;
      pts.forEach(pt=>{const n=Math.abs(pt.x-x); if(n<dist){dist=n;best=pt;}});
      dot.setAttribute("cx",best.x); dot.setAttribute("cy",best.y); lab.textContent=best.v.toFixed(2);
    };
    svg.onpointerdown=pick; svg.onpointermove=e=>{if(e.buttons) pick(e);};
  }
  function mount(id, after){
    let el=document.getElementById(id);
    if(el) return el;
    if(!after) return null;
    el=document.createElement("div"); el.id=id; after.appendChild(el); return el;
  }
  const stack=document.getElementById("eq")?.closest(".card");
  const board=document.getElementById("scoreboard");
  const span=document.getElementById("periodCard");
  const journal=document.getElementById("learnCard");

  async function tick(){
    try{
      const [a,l,h]=await Promise.all([
        fetch("/api/v1/account").then(r=>r.json()),
        fetch("/api/v1/learn").then(r=>r.json()),
        fetch("/api/v1/history/account?limit=48").then(r=>r.json()).catch(()=>({items:[]}))
      ]);
      const k=Number(a.mark), w=Number(a.watch_last||a.mark);
      const row=(sym,px,ref)=>{
        const up=px>=ref; const arrow=up?"▲":"▼"; const cls=up?"up":"dn";
        return '<span class="'+cls+'">'+sym+' '+px.toFixed(0)+' '+arrow+'</span>';
      };
      const t=document.getElementById("tickerText");
      if(t && Number.isFinite(k)){
        t.innerHTML=[row("BTC-USD",k,k),row("BTCUSD",k,k),row("XBTUSD",k,k),row("BTC/USD",k,k),row("BTCUSDT",Number.isFinite(w)?w:k,k),row("BTC-USDT",Number.isFinite(w)?w:k,k)].join("    ·    ")+"    ·    ";
      }
      const eq=(h.items||[]).map(x=>Number(x.equity)).filter(Number.isFinite).reverse();
      const pnl=(l.live_exits&&l.live_exits.series||[]).map(x=>x.cum);
      chart(mount("stackChart",stack), eq.length?eq:pnl);
      chart(mount("boardChart",board), pnl.length?pnl:eq);
      chart(mount("spanChart",span), pnl);
      chart(mount("journalChart",journal), pnl);
    }catch(e){}
  }
  tick(); setInterval(tick, 5000);
})();
