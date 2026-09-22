(function(){
  if(!document.querySelector('script[src="/static/aether-fast.js"]')){
    const s=document.createElement("script");
    s.src="/static/aether-fast.js";
    document.head.appendChild(s);
  }
  function money(n){
    const v=Number(n);
    if(!Number.isFinite(v)) return "\u2014";
    const d=Math.abs(v)<1?4:v>=1000?2:2;
    return v.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:d});
  }
  function closes(series){
    return (series||[]).map(x=>{
      const v=Number(x&&(x.close??x.c??x.last??x.price));
      return Number.isFinite(v)?v:null;
    }).filter(v=>v!=null && v>0);
  }
  function draw(series){
    const host=document.getElementById("assetChart");
    if(!host) return;
    const vals=closes(series);
    if(vals.length<2){
      host.innerHTML='<div class="empty">Waiting for 1m bars.</div>';
      return;
    }
    const w=390,h=168,p=14;
    const min=Math.min.apply(null,vals), max=Math.max.apply(null,vals), span=max-min||1;
    const pts=vals.map((v,i)=>({
      x:p+i*((w-p*2)/Math.max(vals.length-1,1)),
      y:h-p-((v-min)/span)*(h-p*2),
      v
    }));
    const d=pts.map((pt,i)=>(i?"L":"M")+pt.x.toFixed(1)+","+pt.y.toFixed(1)).join(" ");
    const last=pts[pts.length-1];
    const gid="pa"+Date.now();
    const up=vals[vals.length-1]>=vals[0];
    const stroke=up?"#2bc887":"#ef5d6c";
    let grid="";
    for(let i=0;i<5;i++){
      const y=p+i*((h-p*2)/4);
      grid+='<line class="gridline" x1="'+p+'" x2="'+(w-p)+'" y1="'+y+'" y2="'+y+'"/>';
    }
    host.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+stroke+'" stop-opacity=".32"/><stop offset="1" stop-color="'+stroke+'" stop-opacity="0"/></linearGradient></defs>'+grid+'<path fill="url(#'+gid+')" d="'+d+' L'+last.x+','+(h-p)+' L'+pts[0].x+','+(h-p)+' Z"/><path class="chart-stroke" stroke="'+stroke+'" d="'+d+'"/><circle class="dot" fill="#e5b35a" cx="'+last.x+'" cy="'+last.y+'" r="3"/><text fill="#f2f4f7" font-size="10" font-weight="700" x="8" y="12">'+money(last.v)+'</text></svg>';
    const svg=host.querySelector("svg"), dot=host.querySelector(".dot"), lab=host.querySelector("text");
    const pick=ev=>{
      const r=svg.getBoundingClientRect();
      const x=((ev.touches?ev.touches[0].clientX:ev.clientX)-r.left)/r.width*w;
      let best=pts[0], dist=1e9;
      pts.forEach(pt=>{const n=Math.abs(pt.x-x); if(n<dist){dist=n;best=pt;}});
      dot.setAttribute("cx",best.x); dot.setAttribute("cy",best.y); lab.textContent=money(best.v);
    };
    svg.onpointerdown=pick; svg.onpointermove=e=>{if(e.buttons) pick(e);};
  }
  const origFetch=window.fetch;
  window.fetch=function(input,init){
    return origFetch(input,init).then(res=>{
      try{
        const url=typeof input==="string"?input:(input&&input.url)||"";
        if(url.indexOf("/api/v1/assets/")!==-1 && (!init || !init.method || init.method==="GET")){
          res.clone().json().then(data=>{ if(data&&data.series) draw(data.series); }).catch(()=>{});
        }
      }catch(e){}
      return res;
    });
  };
  if(!document.querySelector('script[src="/static/aether-intel.js"]')){
    const s=document.createElement("script");
    s.src="/static/aether-intel.js";
    document.head.appendChild(s);
  }
})();
