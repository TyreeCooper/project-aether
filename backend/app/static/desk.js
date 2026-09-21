(function(){
  const theme=localStorage.getItem("aether-theme")||"dark";
  document.documentElement.setAttribute("data-theme",theme);

  const brandTitle=document.querySelector(".brand-title");
  const brandSub=document.querySelector(".brand-sub");
  if(brandTitle) brandTitle.textContent="AETHER";
  if(brandSub) brandSub.textContent="Paper desk";

  const titles={
    "page-home":["Floor","Kraken paper tape"],
    "page-trade":["Ticket","Place or flatten"],
    "page-activity":["Blotter","Fills as they print"],
    "page-analytics":["Book","Wins, losses, fees"],
    "page-settings":["Booth","Keys, risk, theme"]
  };
  Object.entries(titles).forEach(([id,pair])=>{
    const page=document.getElementById(id);
    if(!page) return;
    const h=page.querySelector(".page-head h1");
    const p=page.querySelector(".page-head p");
    if(h) h.textContent=pair[0];
    if(p) p.textContent=pair[1];
  });

  const dock={
    home:"Floor",trade:"Ticket",activity:"Blotter",analytics:"Book",settings:"Booth"
  };
  document.querySelectorAll(".nav-btn").forEach(btn=>{
    const key=btn.getAttribute("data-page");
    if(dock[key]){
      const label=btn.querySelector("span");
      if(label) label.textContent=dock[key];
    }
  });

  const heads={
    "PORTFOLIO":"Stack",
    "AUTONOMOUS ENGINE":"Engine",
    "PERFORMANCE SNAPSHOT":"Prints",
    "BTC / USD":"Tape",
    "POSITION":"Held",
    "MARKET QUALITY":"Tape age",
    "TRADE LEDGER":"Blotter",
    "AUDIT STREAM":"Wire",
    "PERFORMANCE":"Book",
    "OPERATOR ACCESS":"Access",
    "STRATEGY CONFIG":"Rule",
    "SYSTEM":"Health"
  };
  document.querySelectorAll(".card-head h2").forEach(h=>{
    const next=heads[h.textContent.trim()];
    if(next) h.textContent=next;
  });

  const settings=document.getElementById("page-settings");
  if(settings && !document.getElementById("themeCard")){
    const card=document.createElement("section");
    card.className="card full";
    card.id="themeCard";
    card.innerHTML='<div class="card-head"><h2>LOOK</h2><span class="pill">THEME</span></div>'+
      '<div class="row"><span>Mode</span><span id="themeNow">'+theme+'</span></div>'+
      '<div class="action-grid" style="margin-top:8px">'+
      '<button type="button" class="btn secondary" id="themeDark">Dark</button>'+
      '<button type="button" class="btn secondary" id="themeLight">Light</button></div>'+
      '<div class="hint" style="margin-top:8px">Saved on this phone.</div>';
    settings.querySelector(".grid")?.appendChild(card);
    function setTheme(next){
      document.documentElement.setAttribute("data-theme",next);
      localStorage.setItem("aether-theme",next);
      const now=document.getElementById("themeNow");
      if(now) now.textContent=next;
    }
    document.getElementById("themeDark")?.addEventListener("click",()=>setTheme("dark"));
    document.getElementById("themeLight")?.addEventListener("click",()=>setTheme("light"));
  }
})();
