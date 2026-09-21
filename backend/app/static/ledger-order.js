/* Activity tables: P/L first where applicable; timestamps last. P/L is green / red / white. */
function pnlTone(value){
  const n=Number(value);
  if(!Number.isFinite(n) || Math.abs(n)<1e-9) return "#f5f3fb";
  return n>0 ? "#28c77b" : "#ff5f6d";
}
function pnlCell(value){
  return '<span style="color:'+pnlTone(value)+'">'+esc(money(value))+'</span>';
}
function renderLedger(){
  const rows=historyCache[activeLedger]||[];
  const specs={
    fills:[
      ["Realized P/L",x=>pnlCell(x.realized_pnl_usd)],
      ["Side",x=>esc(x.side)],
      ["Price",x=>esc(money(x.price_usd))],
      ["Qty BTC",x=>esc(num(x.qty_btc,8))],
      ["Fee",x=>esc(money(x.fee_usd))],
      ["Actor",x=>esc(x.actor)],
      ["Exec ID",x=>esc(shortId(x.execution_id))],
      ["Time",x=>esc(clock(x.ts))]
    ],
    orders:[
      ["Side",x=>esc(x.side)],
      ["Qty BTC",x=>esc(num(x.requested_qty_btc,8))],
      ["Status",x=>esc(x.status)],
      ["Actor",x=>esc(x.actor)],
      ["Exec ID",x=>esc(shortId(x.execution_id))],
      ["Time",x=>esc(clock(x.ts))]
    ],
    risk:[
      ["Reason",x=>esc(x.reason)],
      ["Qty",x=>esc(num(x.context&&x.context.requested_qty_btc,8))],
      ["Event",x=>esc(shortId(x.event_key))],
      ["Time",x=>esc(clock(x.ts))]
    ],
    account:[
      ["Realized P/L",x=>pnlCell(x.daily_realized)],
      ["Equity",x=>esc(money(x.equity))],
      ["USD",x=>esc(money(x.usd))],
      ["BTC",x=>esc(num(x.btc,8))],
      ["Time",x=>esc(clock(x.ts))]
    ],
    positions:[
      ["Open P/L",x=>pnlCell(x.open_pnl)],
      ["BTC",x=>esc(num(x.btc,8))],
      ["Mark",x=>esc(money(x.mark))],
      ["Avg entry",x=>esc(money(x.avg_entry))],
      ["State",x=>esc(x.state)],
      ["Time",x=>esc(clock(x.ts))]
    ],
    bot:[
      ["State",x=>esc(x.state)],
      ["Lock",x=>esc(String(x.flatten_lock))],
      ["Strategy",x=>esc(x.strategy)],
      ["Short/Long",x=>esc(x.short_ma+"/"+x.long_ma)],
      ["Stop %",x=>esc(num(x.stop_loss_pct,2))],
      ["Time",x=>esc(clock(x.ts))]
    ]
  };
  const cols=specs[activeLedger];
  if(!rows.length){
    els.ledger.innerHTML='<div class="helper" style="padding:14px">No '+esc(activeLedger)+' records yet.</div>';
    return;
  }
  els.ledger.innerHTML="<table><thead><tr>"+cols.map(c=>"<th>"+esc(c[0])+"</th>").join("")+"</tr></thead><tbody>"+
    rows.map(r=>"<tr>"+cols.map(c=>"<td>"+c[1](r)+"</td>").join("")+"</tr>").join("")+"</tbody></table>";
}
