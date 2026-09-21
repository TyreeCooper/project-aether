"use client";

import { useEffect, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
async function getJson(path){const r=await fetch(`${apiBase}${path}`,{cache:"no-store"});if(!r.ok)throw new Error(path);return r.json();}

export default function DashboardPage(){
  const [floor,setFloor]=useState(null);
  const [error,setError]=useState("");
  useEffect(()=>{let live=true;const load=async()=>{try{const d=await getJson("/api/v1/floor");if(live){setFloor(d);setError("");}}catch{if(live)setError("API unreachable.");}};load();const id=setInterval(load,5000);return()=>{live=false;clearInterval(id);};},[]);
  const p=floor?.portfolio||{};
  return <main className="shell">
    <header className="header"><strong>PROJECT AETHER — MULTI-ASSET DESK</strong><span className="badge">PAPER</span></header>
    {error?<p className="down">{error}</p>:null}
    <section className="card" style={{marginTop:10}}>
      <h2>THE FLOOR</h2>
      <div className="row"><span>Equity</span><span>{p.equity??"-"}</span></div>
      <div className="row"><span>Cash</span><span>{p.cash??"-"}</span></div>
      <div className="row"><span>Invested</span><span>{p.invested??"-"}</span></div>
      <div className="row"><span>Total P/L</span><span>{p.total_pnl??"-"}</span></div>
    </section>
    <section className="card" style={{marginTop:10}}>
      <h2>AETHER VECTOR ENGINE — TEN ASSET BOOKS</h2>
      {(floor?.assets||[]).map(a=><div className="row" key={a.id}><span>{a.pair}</span><span>{a.mark??"-"} · {a.reason||"warming"}</span></div>)}
    </section>
  </main>;
}