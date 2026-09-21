/* Reorder Activity tables: first four columns are the live-trade fields. */
function renderLedger(){
  const rows=historyCache[activeLedger]||[];
  const specs={
    fills:[
      ["Time",x=>clock(x.ts)],
      ["Side",x=>x.side],
      ["Price",x=>money(x.price_usd)],
      ["Realized P/L",x=>money(x.realized_pnl_usd)],
      ["Qty BTC",x=>num(x.qty_btc,8)],
      ["Fee",x=>money(x.fee_usd)],
      ["Actor",x=>x.actor],
      ["Exec ID",x=>shortId(x.execution_id)]
    ],
    orders:[
      ["Time",x=>clock(x.ts)],
      ["Side",x=>x.side],
      ["Qty BTC",x=>num(x.requested_qty_btc,8)],
      ["Status",x=>x.status],
      ["Actor",x=>x.actor],
      ["Exec ID",x=>shortId(x.execution_id)]
    ],
    risk:[
      ["Time",x=>clock(x.ts)],
      ["Reason",x=>x.reason],
      ["Qty",x=>num(x.context&&x.context.requested_qty_btc,8)],
      ["Event",x=>shortId(x.event_key)]
    ],
    account:[
      ["Time",x=>clock(x.ts)],
      ["Equity",x=>money(x.equity)],
      ["Daily",x=>money(x.daily_realized)],
      ["USD",x=>money(x.usd)],
      ["BTC",x=>num(x.btc,8)]
    ],
    positions:[
      ["Time",x=>clock(x.ts)],
      ["Open P/L",x=>money(x.open_pnl)],
      ["BTC",x=>num(x.btc,8)],
      ["Mark",x=>money(x.mark)],
      ["Avg entry",x=>money(x.avg_entry)],
      ["State",x=>x.state]
    ],
    bot:[
      ["Time",x=>clock(x.ts)],
      ["State",x=>x.state],
      ["Lock",x=>String(x.flatten_lock)],
      ["Strategy",x=>x.strategy],
      ["Short/Long",x=>x.short_ma+"/"+x.long_ma],
      ["Stop %",x=>num(x.stop_loss_pct,2)]
    ]
  };
  const cols=specs[activeLedger];
  if(!rows.length){
    els.ledger.innerHTML='<div class="helper" style="padding:14px">No '+esc(activeLedger)+' records yet.</div>';
    return;
  }
  els.ledger.innerHTML="<table><thead><tr>"+cols.map(c=>"<th>"+esc(c[0])+"</th>").join("")+"</tr></thead><tbody>"+
    rows.map(r=>"<tr>"+cols.map(c=>"<td>"+esc(c[1](r))+"</td>").join("")+"</tr>").join("")+"</tbody></table>";
}
