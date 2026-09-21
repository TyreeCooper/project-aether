/* Activity tables: critical columns first; P/L is green / red / white. */
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
      ["Time",x=>esc(clock(x.ts))],
      ["Side",x=>esc(x.side)],
      ["Price",x=>esc(money(x.price_usd))],
      ["Realized P/L",x=>pnlCell(x.realized_pnl_usd)],
      ["Qty BTC",x=>esc(num(x.qty_btc,8))],
      ["Fee",x=>esc(money(x.fee_usd))],
      ["Actor",x=>esc(x.actor)],
      ["Exec ID",x=>esc(shortId(x.execution_id))]
    ],
    orders:[
      ["Time",x=>esc(clock(x.ts))],
      ["Side",x=>esc(x.side)],
      ["Qty BTC",x=>esc(num(x.requested_qty_btc,8))],
      ["Status",x=>esc(x.status)],
      ["Actor",x=>esc(x.actor)],
      ["Exec ID",x=>esc(shortId(x.execution_id))]
    ],
    risk:[
      ["Time",x=>esc(clock(x.ts))],
      ["Reason",x=>esc(x.reason)],
      ["Qty",x=>esc(num(x.context&&x.context.requested_qty_btc,8))],
      ["Event",x=>esc(shortId(x.event_key))]
    ],
    account:[
      ["Time",x=>esc(clock(x.ts))],
      ["Equity",x=>esc(money(x.equity))],
      ["Daily",x=>pnlCell(x.daily_realized)],
      ["USD",x=>esc(money(x.usd))],
      ["BTC",x=>esc(num(x.btc,8))]
    ],
    positions:[
      ["Time",x=>esc(clock(x.ts))],
      ["Open P/L",x=>pnlCell(x.open_pnl)],
      ["BTC",x=>esc(num(x.btc,8))],
      ["Mark",x=>esc(money(x.mark))],
      ["Avg entry",x=>esc(money(x.avg_entry))],
      ["State",x=>esc(x.state)]
    ],
    bot:[
      ["Time",x=>esc(clock(x.ts))],
      ["State",x=>esc(x.state)],
      ["Lock",x=>esc(String(x.flatten_lock))],
      ["Strategy",x=>esc(x.strategy)],
      ["Short/Long",x=>esc(x.short_ma+"/"+x.long_ma)],
      ["Stop %",x=>esc(num(x.stop_loss_pct,2))]
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
