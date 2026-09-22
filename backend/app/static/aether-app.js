(function(){
  const $=id=>document.getElementById(id);
  const state={floor:null,asset:null,live:null,blotter:[],settings:null,token:localStorage.getItem("aether-operator-token")||""};
  const money=n=>{const v=Number(n);if(!Number.isFinite(v))return "—";const d=Math.abs(v)<1?4:2;return "$"+v.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:d});};
  const num=(n,d=4)=>{const v=Number(n);return Number.isFinite(v)?v.toLocaleString("en-US",{maximumFractionDigits:d}):"—";};
  const pct=n=>{const v=Number(n);return Number.isFinite(v)?((v>0?"+":"")+v.toFixed(2)+"%"):"—";};
  const when=v=>{if(!v)return "—";const d=new Date(v);return Number.isFinite(d.getTime())?d.toLocaleString([], {month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}):String(v);};
  const duration=s=>{
    const n=Math.max(0,Math.floor(Number(s)||0));
    if(n<60)return n+"s";
    const d=Math.floor(n/86400),h=Math.floor((n%86400)/3600),m=Math.floor((n%3600)/60),sec=n%60;
    if(d)return d+"d "+h+"h";
    if(h)return h+"h "+m+"m";
    return m+"m "+String(sec).padStart(2,"0")+"s";
  };
  const liveDuration=opened=>{
    if(!opened)return null;
    const t=new Date(opened).getTime();
    return Number.isFinite(t)?Math.max(0,Math.floor((Date.now()-t)/1000)):null;
  };
  const pnlClass=n=>Number(n)>0?"up":Number(n)<0?"down":"";
  const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
  function toast(msg){const e=$("toast");e.textContent=msg;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),1800);}
  async function runButton(btn,pending,fn){
    if(!btn||btn.disabled)return;
    const original=btn.textContent;
    btn.disabled=true;btn.classList.remove("state-success","state-error");btn.classList.add("working");btn.textContent=pending;
    try{
      const out=await fn();
      btn.classList.remove("working");btn.classList.add("state-success");btn.textContent="Done";
      setTimeout(()=>{btn.classList.remove("state-success");btn.disabled=false;btn.textContent=original;},650);
      return out;
    }catch(e){
      btn.classList.remove("working");btn.classList.add("state-error");btn.textContent="Error";
      setTimeout(()=>{btn.classList.remove("state-error");btn.disabled=false;btn.textContent=original;},900);
      throw e;
    }
  }
  async function get(path){const r=await fetch(path,{cache:"no-store"});if(!r.ok)throw new Error(path);return r.json();}
  async function post(path){const headers={};if(state.token)headers["X-Operator-Token"]=state.token;const r=await fetch(path,{method:"POST",headers});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.error||"Request failed");return d;}
  function metric(label,value,cls=""){return '<div class="metric"><span>'+esc(label)+'</span><b class="'+cls+'">'+esc(value)+'</b></div>';}
  function setText(id,v,cls){const e=$(id);if(!e)return;e.textContent=v;if(cls)e.className=cls;}
  function navAssets(){
    const rows=state.floor?.assets||[];
    $("assetNav").innerHTML='<button data-floor="1">FLOOR</button>'+rows.map(a=>'<button data-asset="'+a.id+'">'+esc(a.symbol)+'</button>').join("")+'<button id="addAssetBtn" class="add-asset-btn" type="button" aria-label="Add Kraken asset">＋</button>';
    $("assetNav").querySelector("[data-floor]")?.addEventListener("click",()=>go("floor"));
    $("assetNav").querySelectorAll("[data-asset]").forEach(b=>b.addEventListener("click",()=>go("asset/"+b.dataset.asset)));
    $("addAssetBtn")?.addEventListener("click",openAssetPicker);
    markNav();
  }
  function markNav(){
    const h=location.hash.replace(/^#\/?/,"")||"floor";
    $("assetNav")?.querySelectorAll("button").forEach(b=>b.classList.toggle("on",(h==="floor"&&b.dataset.floor)||(h.startsWith("asset/")&&b.dataset.asset===h.split("/")[1])));
    document.querySelectorAll(".bottom-nav button").forEach(b=>{
      const r=b.dataset.route;
      const on=(r==="assets"&&h.startsWith("asset/"))||h===r;
      b.classList.toggle("on",on);
    });
  }
  function go(route){location.hash="#/"+route;}
  function show(name){
    document.querySelectorAll(".view").forEach(v=>v.classList.add("hidden"));
    $("view-"+name)?.classList.remove("hidden");
    markNav();
  }
  function bars(hostId,rows,valueFn,formatFn){
    const host=$(hostId);if(!host)return;
    const vals=rows.map(valueFn);const max=Math.max(...vals.map(v=>Math.abs(Number(v)||0)),1e-9);
    host.innerHTML=rows.map(r=>{const v=Number(valueFn(r))||0;const w=Math.max(Math.abs(v)/max*100,1);return '<div class="bar-row"><label>'+esc(r.symbol||r.pair)+'</label><div class="track"><div class="fill '+(v>=0?"good":"bad")+'" style="width:'+w+'%"></div></div><output class="'+pnlClass(v)+'">'+esc(formatFn(v))+'</output></div>';}).join("");
  }
  function lineChart(series){
    const host=$("assetChart");if(!host)return;
    const vals=(series||[]).map(x=>Number(x.close)).filter(Number.isFinite);
    if(vals.length<2){host.innerHTML='<div class="empty">Waiting for this asset\'s bars.</div>';return;}
    const w=760,h=230,p=20,min=Math.min(...vals),max=Math.max(...vals),span=max-min||1;
    const pts=vals.map((v,i)=>[p+i*(w-p*2)/(vals.length-1),h-p-(v-min)/span*(h-p*2)]);
    const d=pts.map((q,i)=>(i?"L":"M")+q[0].toFixed(1)+","+q[1].toFixed(1)).join(" ");
    let grid="";for(let i=0;i<5;i++){const y=p+i*(h-p*2)/4;grid+='<line class="gridline" x1="'+p+'" x2="'+(w-p)+'" y1="'+y+'" y2="'+y+'"/>';}
    host.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><defs><linearGradient id="aetherArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7b61ff" stop-opacity=".32"/><stop offset="1" stop-color="#7b61ff" stop-opacity="0"/></linearGradient></defs>'+grid+'<path class="chart-area" d="'+d+' L'+pts[pts.length-1][0]+','+(h-p)+' L'+pts[0][0]+','+(h-p)+' Z"/><path class="chart-stroke" d="'+d+'"/></svg>';
  }
  function renderFloor(){
    const f=state.floor;if(!f)return;const p=f.portfolio||{},rows=f.assets||[];
    setText("floorEquity",money(p.equity));setText("floorPnl",(Number(p.total_pnl)>=0?"+":"")+money(p.total_pnl).replace("$","")+" total P&L",pnlClass(p.total_pnl));
    setText("floorCash",money(p.cash));setText("floorExposure",pct(p.exposure_pct)+" exposure");
    setText("floorInvested",money(p.invested));setText("floorPositions",(p.active_positions||0)+" active positions");
    setText("floorRealized",money(p.realized_pnl),pnlClass(p.realized_pnl));setText("floorTrades",(p.trades||0)+" completed trades");
    const live=state.live||{},open=live.items||[];
    const strip=$("floorLiveStrip");
    if(strip){
      const count=Number(live.open_count??p.active_positions??0);
      setText("floorLiveState",count?(count+" LIVE TRADE"+(count===1?"":"S")):"AETHER SCANNING");
      setText("floorLiveDetail",count?open.slice(0,3).map(x=>x.symbol+" "+String(x.side||"").toUpperCase()+" "+money(x.open_pnl_usd)).join(" · "):"0 open positions · watching all 12 books");
      $("floorLiveDot")?.classList.toggle("active",count>0);
    }
    bars("pnlBars",rows,a=>Number(a.open_pnl||0)+Number(a.analytics?.realized_pnl||0),money);
    bars("allocationBars",rows,a=>Number(a.position_value||0),money);
    bars("breadthBars",rows,a=>Number(a.analytics?.change_pct||0),pct);
    $("allocationTotal").textContent=money(p.invested);
    const intel=f.intelligence||{};const oppRows=intel.opportunity_ranking||[];
    $("floorOpportunityBoard").innerHTML=oppRows.map(a=>'<div class="asset-row intel-row" data-id="'+a.id+'"><b class="pair">'+esc(a.pair)+'</b><span>'+money(a.price)+'</span><span class="'+pnlClass(a.change_24h_pct)+'">'+pct(a.change_24h_pct)+'</span><span>'+pct(a.range_24h_pct)+'</span><span>'+num(a.spread_bps,2)+' bps</span><span>'+esc(String(a.risk_state||"normal").toUpperCase())+'</span></div>').join("");
    $("floorOpportunityBoard").querySelectorAll(".asset-row").forEach(r=>r.onclick=()=>go("asset/"+r.dataset.id));
    const risk=intel.risk||{};$("floorRiskBadge").textContent=String(risk.state||"unknown").toUpperCase();$("floorRiskBadge").className="badge "+(risk.state==="normal"?"good":"amber");
    const cal=f.risk_calendar||{};const macroUpcoming=(cal.upcoming_24h||[]).slice(0,3);const nextEvent=macroUpcoming[0];const cryptoCal=cal.crypto_calendar||{};const cryptoUpcoming=(cryptoCal.events||[]).slice(0,3);const nextCrypto=cryptoUpcoming[0];
    const catalystRows=[];
    macroUpcoming.forEach((e,i)=>catalystRows.push(metric("MACRO "+(i+1),String(e.title||"—")+" · "+when(e.scheduled_at)+" · "+String(e.impact||"—").toUpperCase())));
    cryptoUpcoming.forEach((e,i)=>catalystRows.push(metric("CRYPTO "+(i+1),String(e.title||"—")+" · "+String(e.displayed_date||when(e.scheduled_at))+(e.is_estimated?" · ESTIMATED":""))));
    $("floorCatalysts").innerHTML=catalystRows.length?catalystRows.join(""):metric("Catalysts","No loaded macro/crypto catalysts");
    $("floorRisk").innerHTML=metric("State",String(risk.state||"unknown").toUpperCase())+metric("New entries",risk.new_entries_allowed?"ALLOWED":"RESTRICTED",risk.new_entries_allowed?"up":"down")+metric("Macro feed",risk.calendar_connected?"CONNECTED":"NOT CONNECTED",risk.calendar_connected?"up":"")+metric("Next macro",nextEvent?nextEvent.title:"None in next 24h")+metric("Macro impact",nextEvent?String(nextEvent.impact||"—").toUpperCase():"—")+metric("Primary verification",nextEvent?(nextEvent.verified_official?"VERIFIED":String(nextEvent.official_verification_status||"UNVERIFIED").replaceAll("_"," ").toUpperCase()):"—",nextEvent?.verified_official?"up":"")+metric("Crypto events",String(cryptoCal.status||"unconfigured").toUpperCase(),cryptoCal.connected?"up":"")+metric("Next crypto",nextCrypto?nextCrypto.title:"No tracked event loaded")+metric("Crypto date",nextCrypto?String(nextCrypto.displayed_date||"—"):"—")+metric("Crypto policy","OBSERVE ONLY");
    const sources=intel.sources||[];$("floorSources").innerHTML=metric("Connected",String(sources.filter(x=>x.status==="connected").length))+metric("Planned",String(sources.filter(x=>x.status==="planned").length))+metric("Market",sources.find(x=>x.id==="kraken")?.status?.toUpperCase()||"—")+metric("Macro calendar",sources.find(x=>x.id==="forex_factory")?.status?.toUpperCase()||"—")+metric("Crypto calendar",sources.find(x=>x.id==="coinmarketcal")?.status?.toUpperCase()||"—")+metric("News",sources.find(x=>x.id==="gdelt")?.status?.toUpperCase()||"—")+metric("Community",sources.find(x=>x.id==="community")?.status?.toUpperCase()||"—");
    $("assetBoard").innerHTML=rows.map(a=>'<div class="asset-row" data-id="'+a.id+'"><b class="pair">'+esc(a.pair)+'</b><span>'+money(a.mark)+'</span><span class="'+pnlClass(a.intelligence?.opportunity_24h?.net_change_pct)+'">'+pct(a.intelligence?.opportunity_24h?.net_change_pct)+'</span><span>'+money(a.position_value)+'</span><span class="'+pnlClass(a.open_pnl)+'">'+money(a.open_pnl)+'</span><span>'+esc((a.signal||a.reason||"watch").toUpperCase())+'</span></div>').join("");
    $("assetBoard").querySelectorAll(".asset-row").forEach(r=>r.onclick=()=>go("asset/"+r.dataset.id));
    const e=f.engine||{};const armed=Boolean(e.accepting_entries);const engineLabel=armed?"ARMED":(e.armed&&!e.running?"STARTING":"DISARMED");
    $("floorHealth").innerHTML=metric("Engine",engineLabel,armed?"up":"")+metric("Loop",e.running?"RUNNING":"STOPPED",e.running?"up":"down")+metric("Live execution",f.live_blocked?"BLOCKED":"READY",f.live_blocked?"up":"down")+metric("Books",String(p.assets||0))+metric("Active positions",String(p.active_positions||0))+metric("Exposure",pct(p.exposure_pct));
    $("floorPerformance").innerHTML=metric("Open P&L",money(p.open_pnl),pnlClass(p.open_pnl))+metric("Realized P&L",money(p.realized_pnl),pnlClass(p.realized_pnl))+metric("Fees",money(p.fees))+metric("Win rate",pct(p.win_rate_pct))+metric("W / L",(p.wins||0)+" / "+(p.losses||0));
    $("engineBadge").textContent=armed?"ARMED":(e.armed?"STARTING":"DISARMED");$("engineBadge").className="badge "+(armed?"good":"");
    const ds=$("drawerState");if(ds){ds.textContent=$("engineBadge").textContent;ds.className=$("engineBadge").className;}
  }
  function renderAsset(){
    const d=state.asset;if(!d)return;const a=d.asset||{},an=d.analytics||{},s=d.strategy||{},w=d.window||{};
    setText("assetSymbolBadge",a.symbol||"—");setText("assetName",a.name||"—");setText("assetPair",a.pair||"—");
    setText("assetStateBadge",Number(a.qty)>0?"IN POSITION":"FLAT");$("assetStateBadge").className="badge "+(Number(a.qty)>0?"good":"");
    setText("assetMark",money(a.mark));setText("assetChange",pct(an.change_pct),"delta "+pnlClass(an.change_pct));
    setText("assetBid",money(a.bid));setText("assetAsk",money(a.ask));setText("assetWatch",money(a.watch_last));
    const basis=(Number(a.watch_last)-Number(a.mark));setText("assetBasis",Number.isFinite(basis)?money(basis):"—");
    setText("assetChartTitle",(a.pair||"")+" price");setText("assetWindow",(w.bars||0)+" recent 1m bars");
    lineChart(d.series);
    const held=a.opened_at?liveDuration(a.opened_at):null;
    $("assetPosition").innerHTML=metric("Side",a.side?String(a.side).toUpperCase():"FLAT")+metric("Quantity",num(a.qty,8)+" "+(a.quantity_unit||a.symbol||""))+metric("Average entry",money(a.avg))+metric("Position value",money(a.position_value))+metric("Open P&L",money(a.open_pnl),pnlClass(a.open_pnl))+metric("In trade",held==null?"—":duration(held))+metric("Active stop",money(a.stop));
    $("assetPerformance").innerHTML=metric("Realized P&L",money(an.realized_pnl),pnlClass(an.realized_pnl))+metric("Trades",String(an.trades||0))+metric("Win rate",pct(an.win_rate_pct))+metric("Profit factor",an.profit_factor==null?"—":num(an.profit_factor,2))+metric("Fees",money(an.fees));
    setText("assetSignal",(s.signal||"NO SIGNAL").toUpperCase());$("assetSignal").className="badge "+(s.signal==="buy"?"good":"");
    $("assetStrategy").innerHTML=metric("Strategy","Aether Vector Engine")+metric("Decision",String(s.reason||a.reason||"warming"))+metric("Signal",String(s.signal||"none").toUpperCase())+metric("Quality",s.quality_score==null?"—":String(s.quality_score))+metric("Cost hurdle",s.hurdle_pct==null?"—":pct(s.hurdle_pct));
    $("assetRange").innerHTML=metric("Window high",money(w.high))+metric("Window low",money(w.low))+metric("Book bars",String(a.bars||0))+metric("Kraken pair",String(a.kraken||"—"))+metric("Live execution","BLOCKED","up");
    const intel=d.intelligence||{},opp=intel.opportunity_24h||{},quality=intel.market_quality||{},regime=intel.regime||{},cross=intel.cross_asset||{},attr=intel.attribution||{},news=intel.news||{},comm=intel.community||{},risk=intel.risk||{},cap=d.capture||{};
    $("assetIntelligence").innerHTML=metric("24h open",money(opp.open))+metric("24h high",money(opp.high))+metric("24h low",money(opp.low))+metric("24h net",money(opp.net_move),pnlClass(opp.net_move))+metric("24h change",pct(opp.net_change_pct),pnlClass(opp.net_change_pct))+metric("Opportunity range",money(opp.opportunity_range))+metric("Range %",pct(opp.opportunity_range_pct))+metric("Range position",opp.range_position_pct==null?"—":pct(opp.range_position_pct))+metric("24h volume",num(opp.volume,2))+metric("Relative volume",quality.relative_volume_24h==null?"—":num(quality.relative_volume_24h,2)+"×")+metric("ATR 14 · 1m",quality.atr_14_1m==null?"—":money(quality.atr_14_1m))+metric("Realized vol · 60m",quality.realized_vol_60m_pct==null?"—":pct(quality.realized_vol_60m_pct))+metric("Spread",opp.spread_bps==null?"—":num(opp.spread_bps,2)+" bps")+metric("Liquidity",String(quality.liquidity_state||"unavailable").toUpperCase())+metric("Regime",String(regime.state||"unavailable").replaceAll("_"," ").toUpperCase())+metric("Regime influence",regime.trade_influence_enabled?"ENABLED":"SHADOW ONLY");
    $("assetCrossAsset").innerHTML=metric("BTC correlation 4h",cross.btc_correlation_4h==null?"—":num(cross.btc_correlation_4h,2))+metric("BTC correlation regime",String(cross.btc_correlation_regime||"unavailable").replaceAll("_"," ").toUpperCase())+metric("Beta vs BTC 4h",cross.beta_vs_btc_4h==null?"—":num(cross.beta_vs_btc_4h,2))+metric("ETH correlation 4h",cross.eth_correlation_4h==null?"—":num(cross.eth_correlation_4h,2))+metric("Relative strength vs BTC",cross.relative_strength_vs_btc_24h_pct==null?"—":pct(cross.relative_strength_vs_btc_24h_pct))+metric("Relative strength vs desk",cross.relative_strength_vs_desk_24h_pct==null?"—":pct(cross.relative_strength_vs_desk_24h_pct))+metric("Desk mean 24h",cross.desk_mean_change_24h_pct==null?"—":pct(cross.desk_mean_change_24h_pct))+metric("1h change",pct(intel.windows?.["1h"]?.change_pct))+metric("4h change",pct(intel.windows?.["4h"]?.change_pct))+metric("12h change",pct(intel.windows?.["12h"]?.change_pct))+metric("3d change",pct(intel.windows?.["3d"]?.change_pct))+metric("7d change",pct(intel.windows?.["7d"]?.change_pct))+metric("30d change",pct(intel.windows?.["30d"]?.change_pct));
    const drivers=attr.drivers||[];
    const newsNarratives=news.narratives||[];
    $("assetAttribution").innerHTML=metric("Status",String(attr.status||"unavailable").toUpperCase())+metric("Driver candidates",String(drivers.length))+drivers.slice(0,3).map((x,i)=>metric("Driver "+(i+1),String(x.label||"—")+" · "+String(x.confidence_pct||0)+"%")).join("")+metric("News feed",String(news.status||"unavailable").toUpperCase())+metric("News articles",news.articles_analyzed==null?"—":String(news.articles_analyzed))+metric("News domains",news.independent_domains==null?"—":String(news.independent_domains))+metric("News narrative",newsNarratives[0]?String(newsNarratives[0].term)+" · "+String(newsNarratives[0].mentions):"—")+metric("Note",attr.note||news.note||"—");
    const narratives=comm.narratives||[],manip=comm.manipulation||{};
    $("assetCommunity").innerHTML=metric("Status",String(comm.status||"unavailable").toUpperCase())+metric("Source",comm.source||"—")+metric("Posts analyzed",comm.posts_analyzed==null?"—":String(comm.posts_analyzed))+metric("Sentiment",comm.sentiment==null?"—":String(comm.sentiment))+metric("Confidence",comm.sentiment_confidence?String(comm.sentiment_confidence).toUpperCase():"—")+metric("Top narrative",narratives[0]?String(narratives[0].term)+" · "+String(narratives[0].mentions):"—")+metric("Coordination risk",String(manip.coordination_risk||"unavailable").toUpperCase())+metric("Manipulation risk",manip.manipulation_risk_score==null?"—":num(manip.manipulation_risk_score,1)+"/100")+metric("Duplicate messaging",manip.duplicate_message_ratio==null?"—":pct(Number(manip.duplicate_message_ratio)*100))+metric("Rumor intensity",manip.rumor_intensity==null?"—":num(manip.rumor_intensity,1)+"/100")+metric("Trade influence",comm.trade_influence_enabled?"ENABLED":"SHADOW ONLY")+metric("Note",comm.note||"—");
    $("assetCapture").innerHTML=metric("State",String(cap.state||"none").toUpperCase())+metric("Entry",cap.entry_fill_price==null?"—":money(cap.entry_fill_price))+metric("Exit",cap.exit_fill_price==null?"—":money(cap.exit_fill_price))+metric("MFE",cap.mfe_pct==null?"—":pct(cap.mfe_pct))+metric("MAE",cap.mae_pct==null?"—":pct(cap.mae_pct))+metric("Available move",cap.available_move_pct==null?"—":pct(cap.available_move_pct))+metric("Entry efficiency",cap.entry_efficiency_pct==null?"—":pct(cap.entry_efficiency_pct))+metric("Exit efficiency",cap.exit_efficiency_pct==null?"—":pct(cap.exit_efficiency_pct))+metric("Gross return",cap.gross_return_pct==null?"—":pct(cap.gross_return_pct),pnlClass(cap.gross_return_pct))+metric("Net capture",cap.net_capture_pct==null?"—":pct(cap.net_capture_pct),pnlClass(cap.net_capture_pct))+metric("Capture efficiency",cap.capture_efficiency_pct==null?"—":pct(cap.capture_efficiency_pct))+metric("Missed favorable move",cap.missed_opportunity_pct==null?"—":pct(cap.missed_opportunity_pct))+metric("Fees",cap.fees_usd==null?"—":money(cap.fees_usd))+metric("Slippage",cap.slippage_usd==null?"—":money(cap.slippage_usd))+metric("Cost drag",cap.cost_drag_pct==null?"—":pct(cap.cost_drag_pct))+metric("Purpose","measure capture, not claim perfect fills");
    const assetCal=d.risk_calendar||{};const nextRisk=(assetCal.upcoming_24h||[])[0];const assetCrypto=(assetCal.crypto_calendar?.events||[]).find(e=>(e.coins||[]).some(c=>String(c.symbol||"").toUpperCase()===String(a.symbol||"").toUpperCase()));
    $("assetRisk").innerHTML=metric("State",String(risk.state||"unknown").toUpperCase())+metric("New entries",risk.new_entries_allowed?"ALLOWED":"RESTRICTED",risk.new_entries_allowed?"up":"down")+metric("Macro calendar",risk.calendar_connected?"CONNECTED":"NOT CONNECTED")+metric("Next macro",nextRisk?nextRisk.title:"None in next 24h")+metric("Macro impact",nextRisk?String(nextRisk.impact||"—").toUpperCase():"—")+metric("Primary verification",nextRisk?(nextRisk.verified_official?"VERIFIED":String(nextRisk.official_verification_status||"UNVERIFIED").replaceAll("_"," ").toUpperCase()):"—",nextRisk?.verified_official?"up":"")+metric("Crypto event",assetCrypto?assetCrypto.title:"No tracked event loaded")+metric("Crypto date",assetCrypto?String(assetCrypto.displayed_date||"—"):"—")+metric("Crypto timing",assetCrypto?(assetCrypto.is_estimated?"ESTIMATED WINDOW":"EXACT PROVIDER TIME"):"—")+metric("Policy",assetCal.policy?.mode==="observe_only"?"OBSERVE ONLY":"ACTIVE")+metric("Note",risk.note||"—");
    setText("assetLedgerTitle",(a.pair||"")+" fills");
    const fills=(d.fills||[]).slice().reverse();
    $("assetLedger").innerHTML=fills.length?'<table><thead><tr><th>Time</th><th>Side</th><th>Qty</th><th>Price</th><th>Fee</th><th>P&L</th><th>Actor</th></tr></thead><tbody>'+fills.map(f=>'<tr><td>'+esc(String(f.ts||"").replace("T"," ").slice(0,19))+'</td><td>'+esc(String(f.side||"").toUpperCase())+'</td><td>'+num(f.qty,8)+'</td><td>'+money(f.price)+'</td><td>'+money(f.fee)+'</td><td class="'+pnlClass(f.pnl)+'">'+money(f.pnl)+'</td><td>'+esc(f.actor||"—")+'</td></tr>').join("")+'</tbody></table>':'<div class="empty">No fills yet for '+esc(a.pair||"this asset")+'.</div>';
  }
  function renderEngine(){
    const f=state.floor;if(!f)return;const p=f.portfolio||{},rows=f.assets||[];
    const es=f.engine||{};setText("engineState",es.accepting_entries?"ARMED":(es.armed?"STARTING":"DISARMED"));setText("engineActive",String(p.active_positions||0));setText("engineBookModel","1 / "+String(p.assets||0));
    $("engineMatrix").innerHTML=rows.map(a=>'<div class="asset-row" data-id="'+a.id+'"><b class="pair">'+esc(a.pair)+'</b><span>'+esc(String(a.signal||"NONE").toUpperCase())+'</span><span>'+esc(a.reason||"warming")+'</span><span>'+money(a.open_pnl)+'</span><span>'+num(a.qty,8)+'</span><span>'+money(a.stop)+'</span></div>').join("");
    $("engineMatrix").querySelectorAll(".asset-row").forEach(r=>r.onclick=()=>go("asset/"+r.dataset.id));
  }
  function renderLive(){
    const d=state.live||{},items=d.items||[],watch=d.watch||[],events=d.events||[];
    const openPnl=items.reduce((s,x)=>s+Number(x.open_pnl_usd||0),0);
    setText("liveOpenCount",String(d.open_count||0));
    setText("liveOpenSummary",items.length?items.map(x=>x.symbol+" "+String(x.side||"").toUpperCase()).join(" · "):"Aether is scanning.");
    setText("liveOpenPnl",money(openPnl),pnlClass(openPnl));
    const top=watch[0];
    setText("liveTopWatch",top?String(top.symbol||"—"):"—");
    setText("liveTopWatchDetail",top?(String(top.signal||top.direction||"watch").toUpperCase()+" · "+String(top.quality_score||0)+"/100"):"No qualified setup");
    const engine=state.floor?.engine||{};
    setText("liveEngineState",engine.accepting_entries?"ARMED":(engine.armed?"STARTING":"DISARMED"));
    setText("liveStateBadge",items.length?"TRADING":"SCANNING");
    $("liveStateBadge").className="badge "+(items.length?"good":"");
    $("liveTradeCards").innerHTML=items.length?items.map(t=>{
      const held=liveDuration(t.opened_at);
      return '<article class="live-trade-card" data-asset="'+esc(t.asset_id)+'"><header><div><p class="eyebrow">'+esc(String(t.mode||"trade").toUpperCase())+'</p><h3>'+esc(t.symbol||t.pair||"—")+' <span>'+esc(String(t.side||"").toUpperCase())+'</span></h3></div><b class="live-duration" data-opened="'+esc(t.opened_at||"")+'">'+duration(held??t.duration_seconds)+'</b></header><div class="live-price-row"><div><span>Entry</span><b>'+money(t.entry_price)+'</b></div><div><span>Current</span><b>'+money(t.current_price)+'</b></div><div><span>Stop</span><b>'+money(t.stop_price)+'</b></div></div><div class="live-pnl '+pnlClass(t.open_pnl_usd)+'">'+money(t.open_pnl_usd)+' <small>'+pct(t.price_move_pct)+'</small></div><div class="metric-list">'+metric("MFE",t.mfe_pct==null?"—":pct(t.mfe_pct))+metric("MAE",t.mae_pct==null?"—":pct(t.mae_pct))+metric("Quantity",num(t.quantity,8)+" "+String(t.quantity_unit||""))+metric("Management",String(t.management_state||"MANAGING"))+metric("Entry reason",String(t.entry_reason||"—"))+'</div></article>';
    }).join(""):'<div class="empty live-empty"><b>AETHER SCANNING</b><span>No paper position is open right now. Valid setups can appear below while Aether waits for an executable trigger.</span></div>';
    $("liveTradeCards").querySelectorAll("[data-asset]").forEach(x=>x.onclick=()=>go("asset/"+x.dataset.asset));
    $("liveWatch").innerHTML=watch.length?watch.slice(0,5).map((x,i)=>metric((i+1)+". "+String(x.symbol||x.pair||"—"),String(x.signal||x.direction||"WATCH").toUpperCase()+" · "+String(x.quality_score||0)+"/100 · "+String(x.reason||"waiting"))).join(""):metric("Watch","No setup data yet");
    $("liveEvents").innerHTML=events.length?events.slice(0,12).map(e=>'<div class="event-row"><span>'+esc(when(e.ts))+'</span><b>'+esc(String(e.event_type||"event").replaceAll("_"," ").toUpperCase())+'</b><em>'+esc(e.symbol||e.pair||"—")+'</em></div>').join(""):'<div class="empty">No trade lifecycle events yet.</div>';
  }
  function renderBlotter(){
    const rows=state.blotter||[];
    $("deskBlotter").innerHTML=rows.length?'<table><thead><tr><th>Net P&L</th><th>Asset</th><th>Side</th><th>Mode</th><th>Entry</th><th>Exit</th><th>Duration</th><th>Return</th><th>Fees</th><th>Exit reason</th><th>Closed</th></tr></thead><tbody>'+rows.map(t=>'<tr><td class="'+pnlClass(t.realized_pnl_usd)+'">'+money(t.realized_pnl_usd)+'</td><td><b>'+esc(t.pair||t.symbol||"—")+'</b></td><td>'+esc(String(t.side||"").toUpperCase())+'</td><td>'+esc(String(t.mode||"—").toUpperCase())+'</td><td>'+money(t.entry_price)+'</td><td>'+money(t.exit_price)+'</td><td>'+esc(t.duration_seconds==null?"—":duration(t.duration_seconds))+'</td><td class="'+pnlClass(t.net_return_pct)+'">'+(t.net_return_pct==null?"—":pct(t.net_return_pct))+'</td><td>'+money(t.fees_usd)+'</td><td>'+esc(String(t.exit_reason||"—").replaceAll("_"," "))+'</td><td>'+esc(when(t.closed_at))+'</td></tr>').join("")+'</tbody></table>':'<div class="empty">No completed round-trip paper trades yet.</div>';
  }
  function openAssetPicker(){
    $("assetPicker").classList.remove("hidden");
    $("assetSearch").value="";
    $("assetSearchResults").innerHTML="";
    $("assetSearchStatus").textContent="Type to search Kraken's live crypto/USD spot library.";
    setTimeout(()=>$("assetSearch").focus(),30);
  }
  function closeAssetPicker(){$("assetPicker").classList.add("hidden");}
  let assetSearchTimer=null;
  async function searchKrakenAssets(query){
    const q=String(query||"").trim();
    if(!q){$("assetSearchResults").innerHTML="";$("assetSearchStatus").textContent="Type to search Kraken's live crypto/USD spot library.";return;}
    $("assetSearchStatus").textContent="Searching Kraken…";
    try{
      const data=await get("/api/v1/kraken/assets?q="+encodeURIComponent(q)+"&limit=40");
      const rows=data.items||[];
      $("assetSearchStatus").textContent=rows.length?rows.length+" Kraken pair"+(rows.length===1?"":"s")+" found":"No matching online Kraken USD spot pairs.";
      $("assetSearchResults").innerHTML=rows.map(a=>'<div class="picker-row"><div><b>'+esc(a.symbol)+'</b><span>'+esc(a.wsname||a.pair)+'</span><small>'+esc(a.kraken)+'</small></div><button type="button" class="action '+(a.already_added?"":"primary")+'" data-kraken="'+esc(a.kraken)+'" '+(a.already_added?"disabled":"")+'>'+(a.already_added?"Added":"Add")+'</button></div>').join("");
      $("assetSearchResults").querySelectorAll("button[data-kraken]:not(:disabled)").forEach(btn=>btn.onclick=()=>addKrakenAsset(btn.dataset.kraken,btn));
    }catch(e){$("assetSearchStatus").textContent="Kraken asset search is temporarily unavailable.";}
  }
  async function addKrakenAsset(pair,button){
    if(!state.token){toast("Connect operator access in Booth before adding assets.");return;}
    try{
      await runButton(button,"Adding…",async()=>{
        const headers={"Content-Type":"application/json","X-Operator-Token":state.token};
        const r=await fetch("/api/v1/assets",{method:"POST",headers,body:JSON.stringify({kraken_pair:pair})});
        const d=await r.json().catch(()=>({}));
        if(!r.ok)throw new Error(d.detail||d.error||"Could not add asset");
        await loadFloor();
        const id=d.asset?.asset?.id;
        closeAssetPicker();
        toast((d.already_added?"Already added: ":"Asset book added: ")+(d.asset?.asset?.pair||pair));
        if(id)go("asset/"+id);
      });
    }catch(e){toast(e.message||"Could not add asset");}
  }
  $("closeAssetPicker")?.addEventListener("click",closeAssetPicker);
  $("assetPicker")?.addEventListener("click",e=>{if(e.target===$("assetPicker"))closeAssetPicker();});
  $("assetSearch")?.addEventListener("input",e=>{clearTimeout(assetSearchTimer);assetSearchTimer=setTimeout(()=>searchKrakenAssets(e.target.value),250);});

  function openDrawer(){
    $("drawer").classList.add("open");$("drawerScrim").classList.add("open");$("menuBtn").classList.add("open");$("menuBtn").setAttribute("aria-expanded","true");
  }
  function closeDrawer(){
    $("drawer").classList.remove("open");$("drawerScrim").classList.remove("open");$("menuBtn").classList.remove("open");$("menuBtn").setAttribute("aria-expanded","false");
  }
  $("menuBtn")?.addEventListener("click",()=>$("drawer").classList.contains("open")?closeDrawer():openDrawer());
  $("drawerScrim")?.addEventListener("click",closeDrawer);
  document.querySelectorAll("[data-drawer-route]").forEach(b=>b.addEventListener("click",()=>{closeDrawer();go(b.dataset.drawerRoute);}));

  function renderSettings(){
    const s=state.settings;if(!s)return;const d=s.desk||{},e=s.engine||{},x=s.execution||{},sec=s.security||{},live=s.live||{};
    const armed=Boolean(e.accepting_entries);
    setText("settingsArmedBadge",armed?"ARMED":(e.armed?"STARTING":"DISARMED"));$("settingsArmedBadge").className="badge "+(armed?"good":"");
    $("settingsEngineState").innerHTML=metric("Accepting entries",armed?"YES":"NO",armed?"up":"")+metric("Engine loop",e.running?"RUNNING":"STOPPED",e.running?"up":"down")+metric("State source",e.source||"multi_asset_desk")+metric("Live execution",e.live_blocked?"BLOCKED":"READY",e.live_blocked?"up":"down");
    $("settingAllocation").value=d.allocation_per_entry_pct??8;
    $("settingPoll").value=d.quote_poll_seconds??20;
    $("settingsExecution").innerHTML=metric("Taker fee",pct(x.taker_fee_pct))+metric("Slippage",num(x.slippage_bps,1)+" bps")+metric("Max spread",num(x.max_spread_bps,1)+" bps")+metric("Max watch basis",money(x.max_basis_usd));
    $("settingsData").innerHTML=metric("Primary venue",s.venue||"Kraken")+metric("Watch venue",s.watch_venue||"Binance.US")+metric("Asset books",String(s.assets||0))+metric("Poll cadence",(d.quote_poll_seconds||"—")+" sec")+metric("State persistence",d.state_persistence?"ON":"OFF")+metric("Resume armed state",d.resume_armed_after_restart?"ON":"OFF");
    const intel=s.intelligence||{},intelSources=intel.sources||[],cryptoIntel=intel.crypto_calendar||{},officialMacro=intel.official_macro_sources||{},assetSources=intel.asset_source_registry||{},trust=assetSources.trust_states||{},health=intel.health||{};
    $("settingsIntelligence").innerHTML=metric("Market health",String(health.market?.state||"unavailable").toUpperCase(),health.market?.state==="healthy"?"up":"")+metric("Macro health",String(health.macro_calendar?.state||"unavailable").toUpperCase(),health.macro_calendar?.state==="healthy"?"up":"")+metric("News health",String(health.news?.state||"unavailable").toUpperCase(),health.news?.state==="healthy"?"up":"")+metric("News coverage",health.news?.coverage_pct==null?"—":num(health.news.coverage_pct,1)+"%")+metric("Community health",String(health.community?.state||"unavailable").toUpperCase(),health.community?.state==="healthy"?"up":"")+metric("Community feed coverage",health.community?.coverage_pct==null?"—":num(health.community.coverage_pct,1)+"%")+metric("Macro calendar",intel.macro_calendar_connected?"CONNECTED":"DEGRADED",intel.macro_calendar_connected?"up":"down")+metric("BLS primary",String(officialMacro.bls?.status||"unavailable").toUpperCase(),officialMacro.bls?.connected?"up":"")+metric("Federal Reserve primary",String(officialMacro.federal_reserve?.status||"planned").toUpperCase())+metric("BEA primary",String(officialMacro.bea?.status||"planned").toUpperCase())+metric("Crypto calendar",String(cryptoIntel.status||"unconfigured").toUpperCase(),cryptoIntel.connected?"up":"")+metric("Crypto events loaded",String(cryptoIntel.events_loaded||0))+metric("Crypto trade influence",cryptoIntel.trade_influence_enabled?"ENABLED":"SHADOW ONLY")+metric("Community coverage",String((intel.community_assets_configured||[]).length)+" assets")+metric("Asset source registry",String(assetSources.sources||0)+" sources")+metric("Trusted sources",String(trust.trusted||0))+metric("Candidate sources",String(trust.candidate||0))+metric("Disabled sources",String(trust.disabled||0))+metric("Community trade influence",intel.community_trade_influence_enabled?"ENABLED":"SHADOW ONLY")+metric("Event policy",String(intel.event_policy?.mode||"observe_only").toUpperCase())+metric("Connected sources",String(intelSources.filter(x=>x.status==="connected").length))+metric("Planned sources",String(intelSources.filter(x=>x.status==="planned").length));
    $("settingsSecurity").innerHTML=metric("Operator token",sec.operator_token_configured?"CONFIGURED":"NOT CONFIGURED",sec.operator_token_configured?"up":"down")+metric("Mutations protected",sec.mutations_protected?"YES":"NO",sec.mutations_protected?"up":"down");
    $("settingsAuthBadge").textContent=state.token?"CONNECTED":"LOCKED";$("settingsAuthBadge").className="badge "+(state.token?"good":"bad");
    $("settingsLiveBadge").textContent=live.live_blocked?"BLOCKED":"READY";$("settingsLiveBadge").className="badge "+(live.live_blocked?"amber":"good");
    $("settingsLive").innerHTML=metric("Kraken keys",live.keys_present?"PRESENT":"NOT PRESENT",live.keys_present?"up":"")+metric("Live flag",live.live_flag?"ON":"OFF")+metric("Orders enabled",live.orders_enabled?"YES":"NO",live.orders_enabled?"down":"up")+metric("Safety state",live.live_blocked?"LIVE BLOCKED":"LIVE READY",live.live_blocked?"up":"down")+metric("Status",live.reason||"—");
  }
  async function loadSettings(){state.settings=await get("/api/v1/settings");renderSettings();}
  async function loadLive(){state.live=await get("/api/v1/desk/live-trades");renderLive();renderFloor();}
  async function loadFloor(){const [floor,live]=await Promise.all([get("/api/v1/floor"),get("/api/v1/desk/live-trades").catch(()=>state.live)]);state.floor=floor;if(live)state.live=live;navAssets();renderFloor();renderEngine();if(state.live)renderLive();}
  async function loadAsset(id){state.asset=await get("/api/v1/assets/"+encodeURIComponent(id));renderAsset();}
  async function loadBlotter(){const d=await get("/api/v1/desk/blotter?limit=300");state.blotter=d.items||[];renderBlotter();}
  async function route(){
    const r=location.hash.replace(/^#\/?/,"")||"floor";
    try{
      if(!state.floor)await loadFloor();
      if(r.startsWith("asset/")){const id=r.split("/")[1];show("asset");await loadAsset(id);}
      else if(r==="engine"){show("engine");renderEngine();}
      else if(r==="live"){show("live");await loadLive();}
      else if(r==="blotter"){show("blotter");await loadBlotter();}
      else if(r==="booth"){show("booth");}
      else if(r==="settings"){show("settings");await loadSettings();}
      else if(r==="assets"){const first=state.floor?.assets?.[0]?.id||"btc";go("asset/"+first);return;}
      else{show("floor");renderFloor();}
      markNav();
    }catch(e){toast("Data refresh failed");}
  }
  document.querySelectorAll(".bottom-nav button").forEach(b=>b.onclick=()=>go(b.dataset.route));
  $("floorLiveStrip")?.addEventListener("click",()=>go("live"));
  $("backFloor").onclick=()=>go("floor");
  $("connectOperator").onclick=async()=>{try{await runButton($("connectOperator"),"Connecting…",async()=>{state.token=$("operatorToken").value.trim();localStorage.setItem("aether-operator-token",state.token);await post("/api/v1/auth/verify");$("authBadge").textContent="CONNECTED";$("authBadge").className="badge good";if($("settingsOperatorToken"))$("settingsOperatorToken").value=state.token;toast("Operator connected");});}catch(e){$("authBadge").textContent="LOCKED";$("authBadge").className="badge bad";toast("Authentication failed");}};
  $("armDesk").onclick=async()=>{try{await runButton($("armDesk"),"Arming…",async()=>{await post("/api/v1/desk/arm");await loadFloor();toast("Aether Vector Engine armed");});}catch(e){toast(e.message);}};
  $("disarmDesk").onclick=async()=>{try{await runButton($("disarmDesk"),"Disarming…",async()=>{await post("/api/v1/desk/disarm");await loadFloor();toast("Engine disarmed");});}catch(e){toast(e.message);}};
  $("settingsArm").onclick=async()=>{try{await runButton($("settingsArm"),"Arming…",async()=>{await post("/api/v1/desk/arm");await loadFloor();await loadSettings();toast("Engine armed");});}catch(e){toast(e.message);}};
  $("settingsDisarm").onclick=async()=>{try{await runButton($("settingsDisarm"),"Disarming…",async()=>{await post("/api/v1/desk/disarm");await loadFloor();await loadSettings();toast("Engine disarmed");});}catch(e){toast(e.message);}};
  $("saveDeskSettings").onclick=async()=>{try{await runButton($("saveDeskSettings"),"Saving…",async()=>{const headers={"Content-Type":"application/json"};if(state.token)headers["X-Operator-Token"]=state.token;const body={allocation_per_entry_pct:Number($("settingAllocation").value),quote_poll_seconds:Number($("settingPoll").value)};const r=await fetch("/api/v1/settings",{method:"POST",headers,body:JSON.stringify(body)});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||"Save failed");await loadSettings();await loadFloor();toast("Trading settings saved");});}catch(e){toast(e.message);}};
  $("settingsConnectOperator").onclick=async()=>{try{await runButton($("settingsConnectOperator"),"Connecting…",async()=>{state.token=$("settingsOperatorToken").value.trim();localStorage.setItem("aether-operator-token",state.token);await post("/api/v1/auth/verify");$("operatorToken").value=state.token;await loadSettings();toast("Operator connected");});}catch(e){toast("Authentication failed");}};
  $("settingsDisconnectOperator").onclick=()=>{state.token="";localStorage.removeItem("aether-operator-token");$("settingsOperatorToken").value="";$("operatorToken").value="";renderSettings();toast("Operator disconnected");};
  if(state.token){$("operatorToken").value=state.token;$("settingsOperatorToken").value=state.token;}
  addEventListener("hashchange",route);
  setInterval(()=>{const d=new Date();$("floorClock").textContent=d.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"});document.querySelectorAll(".live-duration[data-opened]").forEach(el=>{const seconds=liveDuration(el.dataset.opened);if(seconds!=null)el.textContent=duration(seconds);});},1000);
  route();
  setInterval(async()=>{try{await loadFloor();const r=location.hash.replace(/^#\/?/,"");if(r.startsWith("asset/"))await loadAsset(r.split("/")[1]);if(r==="live")await loadLive();if(r==="blotter")await loadBlotter();}catch(e){}},8000);
})();