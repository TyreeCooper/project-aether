(function(){
  const money=n=>{const v=Number(n);if(!Number.isFinite(v))return "\u2014";const d=Math.abs(v)<1?4:2;return v.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:d});};
  const show=v=>{
    if(v==null || v==="") return "\u2014";
    if(typeof v==="number" && Number.isFinite(v)){
      if(Math.abs(v)>=1000) return money(v);
      return String(Math.round(v*10000)/10000);
    }
    return String(v);
  };
  function esc(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&","<":"<",">":">",'"':""","'":"&#39;"}[m]));}
  function paint(intel, broker){
    const host=document.getElementById("assetIntel");
    if(!host || !intel) return;
    const skin=broker||{};
    const cards=intel.cards||[];
    const logo=skin.logo?'<div class="broker-mark"><img src="'+esc(skin.logo)+'" alt="'+esc(skin.label||"broker")+'"/></div>':'';
    host.innerHTML=logo+cards.map(c=>{
      return '<article class="intel-card '+(c.tone||'')+'"><p class="intel-kicker">'+esc(c.title)+'</p><h3>'+esc(String(c.headline??c.slang??""))+'</h3><p class="intel-plain"><b>'+esc(c.slang||"")+'.</b> '+esc(c.plain||"")+'</p>'+(c.fields||[]).map(f=>'<div class="intel-row"><span>'+esc(f.label)+'<small>'+esc(f.means)+'</small></span><b>'+esc(show(f.value))+(f.unit?" "+esc(f.unit):"")+'</b></div>').join("")+'</article>';
    }).join("")+'<p class="intel-note">Same pack the bot reads. Signal '+esc(String(intel.call||""))+' \u00b7 reason '+esc(String(intel.reason||""))+'.</p>';
    const page=document.getElementById("view-asset");
    if(page && skin.id){
      page.setAttribute("data-broker", skin.id);
      page.style.removeProperty("--broker");
    }
    const head=document.querySelector(".asset-page-head") || document.querySelector(".asset-identity");
    if(head && skin.logo && !head.querySelector(".broker-mark")){
      const wrap=document.createElement("div");
      wrap.className="broker-mark";
      wrap.innerHTML='<img src="'+esc(skin.logo)+'" alt="'+esc(skin.label||"broker")+'"/>';
      head.appendChild(wrap);
    }else if(head && skin.logo){
      const img=head.querySelector(".broker-mark img");
      if(img) img.src=skin.logo;
    }
  }
  function ensure(){
    if(document.getElementById("assetIntel")) return;
    const chart=document.querySelector(".asset-chart-panel");
    const board=document.createElement("section");
    board.id="assetIntel"; board.className="intel-board";
    if(chart) chart.after(board);
    document.querySelectorAll("#view-asset .dashboard-grid").forEach(el=>el.classList.add("asset-extra"));
  }
  const orig=window.fetch;
  window.fetch=function(input,init){
    return orig(input,init).then(res=>{
      try{
        const url=typeof input==="string"?input:(input&&input.url)||"";
        if(url.indexOf("/api/v1/assets/")!==-1){
          res.clone().json().then(data=>{ ensure(); if(data&&data.intel) paint(data.intel, data.broker); }).catch(()=>{});
        }
      }catch(e){}
      return res;
    });
  };
  function link(id, href){
    if(document.getElementById(id)) return;
    const l=document.createElement("link"); l.id=id; l.rel="stylesheet"; l.href=href; document.head.appendChild(l);
  }
  link("intelCss","/static/aether-intel.css");
  link("brokerCss","/static/aether-broker.css");
})();
