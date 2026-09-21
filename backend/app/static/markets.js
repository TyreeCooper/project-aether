(function(){
  const KEY="aether-asset";
  let assets=[];
  let selected=localStorage.getItem(KEY)||"btc";
  let tvWidget=null;

  function money(n){
    const v=Number(n);
    if(!Number.isFinite(v)) return "\u2014";
    const d=v>=1000?2:v>=1?4:6;
    return v.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:d});
  }

  function current(){
    return assets.find(a=>a.id===selected)||assets[0];
  }

  function ensureRail(){
    if(document.getElementById("assetRail")) return document.getElementById("assetRail");
    const rail=document.createElement("div");
    rail.id="assetRail";
    rail.className="asset-rail";
    const tape=document.getElementById("ticker");
    if(tape) tape.after(rail);
    else document.querySelector(".topbar")?.after(rail);
    return rail;
  }

  function ensureCard(){
    let card=document.getElementById("assetCard");
    if(card) return card;
    card=document.createElement("section");
    card.id="assetCard";
    card.className="card full market-hero asset-card";
    card.innerHTML='<div class="asset-card-top"><div><p class="symbol-title" id="assetPair">BTC/USD</p><p class="asset-name" id="assetName">Bitcoin</p></div><span class="asset-chip" id="assetMode">PAPER</span></div><div class="price" id="assetLast">\u2014</div><div class="asset-quote"><span>Bid <b id="assetBid">\u2014</b></span><span>Ask <b id="assetAsk">\u2014</b></span></div>';
    const home=document.getElementById("page-home")||document.querySelector(".page.active")||document.body;
    const hero=home.querySelector(".market-hero");
    if(hero) hero.after(card);
    else home.prepend(card);
    return card;
  }

  function paintRail(){
    const rail=ensureRail();
    rail.innerHTML=assets.map(a=>{
      const on=a.id===selected?" on":"";
      const px=a.last==null?"":"<em>"+money(a.last)+"</em>";
      return '<button type="button" class="asset-pill'+on+'" data-id="'+a.id+'">'+a.symbol+px+"</button>";
    }).join("");
    rail.querySelectorAll(".asset-pill").forEach(btn=>{
      btn.onclick=()=>select(btn.getAttribute("data-id"));
    });
  }

  function paintCard(){
    const a=current();
    if(!a) return;
    ensureCard();
    const set=(id,v)=>{const el=document.getElementById(id); if(el) el.textContent=v;};
    set("assetPair", a.pair|| (a.symbol+"/USD"));
    set("assetName", a.name||a.symbol);
    set("assetLast", money(a.last));
    set("assetBid", money(a.bid));
    set("assetAsk", money(a.ask));
    const mode=document.getElementById("assetMode");
    if(mode) mode.textContent=a.paper?"PAPER FILL":"WATCH";
    const title=document.querySelector(".symbol-title");
    if(title && title.id!=="assetPair") title.textContent=a.pair||title.textContent;
    const price=document.querySelector(".market-hero .price");
    if(price && a.last!=null) price.textContent="$"+money(a.last);
  }

  function bootTv(symbol){
    const host=document.getElementById("tvKraken");
    if(!host || !window.TradingView) return;
    host.innerHTML="";
    const dark=document.documentElement.getAttribute("data-theme")!=="light";
    tvWidget=new window.TradingView.widget({
      autosize:true,
      symbol:symbol,
      interval:"60",
      timezone:"Etc/UTC",
      theme:dark?"dark":"light",
      style:"1",
      locale:"en",
      container_id:"tvKraken",
      hide_legend:false,
      allow_symbol_change:false
    });
  }

  function select(id){
    selected=id;
    localStorage.setItem(KEY,id);
    const a=current();
    paintRail();
    paintCard();
    if(a && a.tv) bootTv(a.tv);
  }

  async function load(){
    try{
      const res=await fetch("/api/v1/markets");
      const data=await res.json();
      assets=data.items||[];
      if(!assets.some(a=>a.id===selected)) selected="btc";
      paintRail();
      paintCard();
      const a=current();
      if(a && window.TradingView) bootTv(a.tv);
    }catch(e){}
  }

  const waitTv=()=>{
    if(window.TradingView){
      const a=current();
      if(a) bootTv(a.tv);
      return;
    }
    setTimeout(waitTv,400);
  };
  load();
  waitTv();
  setInterval(load,15000);
})();
