"""AETHER Pipeline Maintenance self-diagnosis and bounded PAPER self-healing."""
from __future__ import annotations
import asyncio, hashlib, inspect, os, re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import sqlalchemy as sa
from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.kraken_ingress_supervisor import maintenance_quarantine_symbols, maintenance_quarantine_snapshot
from aether_vnext.store import VNextStore

UTC=timezone.utc
MAINTENANCE_VERSION="maintenance-agent-v1"
HEALTHY_PROFILE_VERSION="HealthyPipelineProfile-v1"
CONTROL_DEFAULTS={
 "master_enabled":True,
 "diagnostics_enabled":True,
 "first_clog_enabled":True,
 "incident_history_enabled":True,
 "auto_repair_enabled":False,
 "level1_safe_repair_enabled":True,
 "level2_guarded_tuning_enabled":False,
 "code_repair_planning_enabled":False,
 "unsupported_symbol_quarantine_enabled":True,
}
CONTROL_LABELS={
 "master_enabled":"Maintenance Agent",
 "diagnostics_enabled":"Detailed diagnostics",
 "first_clog_enabled":"First causal clog detection",
 "incident_history_enabled":"Incident history",
 "auto_repair_enabled":"Automatic repair",
 "level1_safe_repair_enabled":"Level 1 safe repairs",
 "level2_guarded_tuning_enabled":"Level 2 guarded tuning",
 "code_repair_planning_enabled":"Code repair planning",
 "unsupported_symbol_quarantine_enabled":"Unsupported-symbol quarantine",
}
_UNSUPPORTED_RE=re.compile(r"Currency pair not supported\s+([A-Z0-9._/-]+)",re.I)

@dataclass(frozen=True,slots=True)
class MaintenanceStatus:
    enabled:bool; running:bool; paper_only:bool; live_blocked:bool
    cycle_count:int; interval_seconds:float
    last_cycle_started_at_utc:str|None; last_cycle_finished_at_utc:str|None
    last_error:str|None; last_result:dict[str,object]|None

def _reasons(ingress:Mapping[str,object])->Counter[str]:
    rows=(ingress.get("last_result") or {}).get("asset_results") or []
    return Counter(str(r.get("reason") or "unknown") for r in rows if isinstance(r,Mapping) and r.get("executable") is not True)

def _unsupported(ingress:Mapping[str,object])->tuple[str,...]:
    found=set()
    for row in (ingress.get("last_result") or {}).get("batch_errors") or []:
        if isinstance(row,Mapping):
            m=_UNSUPPORTED_RE.search(str(row.get("error") or ""))
            if m: found.add(m.group(1).upper())
    return tuple(sorted(found))

def diagnose_pipeline(*,ingress:Mapping[str,object],discovery:Mapping[str,object],strategy:Mapping[str,object],floor:Mapping[str,object]|None=None)->dict[str,object]:
    disc=discovery.get("last_result") or {}; strat=strategy.get("last_result") or {}; pipe=strat.get("pipeline") or {}
    admitted=int(disc.get("focus_admitted_count") or disc.get("focus_count") or 0)
    roaming=int(pipe.get("roaming_batch") or 0); market=int(pipe.get("market_ready") or 0)
    history=int(pipe.get("history_ready") or 0); evaluated=int(pipe.get("strategy_evaluated") or 0)
    watch=int(pipe.get("watch") or 0); fire=int(pipe.get("fire_or_beyond") or 0)
    reasons=_reasons(ingress); unsupported=_unsupported(ingress)
    rows=(ingress.get("last_result") or {}).get("asset_results") or []
    executable=sum(1 for r in rows if isinstance(r,Mapping) and r.get("executable") is True)
    attempted=len(rows)
    status="CLEAR"; edge="PIPELINE"; owner="Maintenance"; reason="healthy_or_no_natural_setup"
    observed="No first causal infrastructure clog detected."; affected=0; not_root=[]; downstream=[]; confidence="MEDIUM"
    faults=[]
    for name,p in (("ingress",ingress),("discovery",discovery),("strategy",strategy)):
        if p.get("enabled") is False: faults.append(name+"_disabled")
        elif p.get("running") is not True: faults.append(name+"_not_running")
        if p.get("last_error"): faults.append(name+":"+str(p.get("last_error")))
    if faults:
        status="FAULT"; edge="RUNTIME"; owner="Runtime Supervisor"; reason=faults[0]; observed="; ".join(faults[:4]); affected=admitted or attempted; confidence="HIGH"
    elif admitted>0 and roaming==0:
        status="BLOCKED"; edge="FOCUS_ADMITTED→ROAMING_SCAN"; owner="Runtime Product Binding"; reason="no_roaming_candidates"; observed=f"{admitted} admitted; 0 selected for deep evaluation."; affected=admitted; downstream=["MARKET_READY","HISTORY_READY","STRATEGY_EVALUATED","WATCH"]; confidence="HIGH"
    elif roaming>0 and market==0:
        status="BLOCKED"; edge="ROAMING_SCAN→MARKET_READY"; owner="Market Ingress"; reason=reasons.most_common(1)[0][0] if reasons else "market_not_ready"; observed=f"{roaming} scanning; 0 market-ready. Ingress executable={executable}/{attempted}."; affected=max(roaming,attempted-executable); downstream=["HISTORY_READY","STRATEGY_EVALUATED","WATCH","FIRE","SIZE","READY","OPEN"]; not_root=["History","Scout","Sniper","Risk","Clerk","Portfolio"]; confidence="HIGH"
    elif market>0 and history==0:
        status="BLOCKED"; edge="MARKET_READY→HISTORY_READY"; owner="History / Warm-up"; reason="history_not_ready"; observed=f"{market} market-ready; 0 history-ready."; affected=market; downstream=["STRATEGY_EVALUATED","WATCH","OPEN"]; not_root=["Scout","Risk","Clerk","Portfolio"]; confidence="HIGH"
    elif history>0 and evaluated==0:
        status="BLOCKED"; edge="HISTORY_READY→STRATEGY_EVALUATED"; owner="Strategy Supervisor"; reason="evaluation_not_advancing"; observed=f"{history} history-ready; 0 evaluated."; affected=history; downstream=["WATCH","FIRE","OPEN"]; confidence="HIGH"
    elif evaluated>0 and watch==0:
        errors=int(pipe.get("evaluation_error") or 0)
        if errors:
            status="DEGRADED"; edge="STRATEGY_EVALUATED→WATCH"; owner="Scout / Strategy"; reason="evaluation_errors_present"; observed=f"{evaluated} evaluated; 0 WATCH; {errors} evaluation errors."; affected=errors; confidence="HIGH"
        else:
            status="CLEAR"; edge="STRATEGY_EVALUATED→WATCH"; owner="Scout"; reason="no_natural_setup"; observed=f"{evaluated} assets evaluated; no natural setup qualified."; confidence="HIGH"
    recommendation={
      "quote_stale":"Inspect ingress cycle duration and process provider batches before quotes age out; do not loosen strategy filters.",
      "history_not_ready":"Inspect warm-up coverage and per-asset history reasons before touching Scout.",
      "no_roaming_candidates":"Inspect runtime product/playbook commissioning between admission and deep scan.",
      "evaluation_not_advancing":"Inspect route-clock/evaluator errors.",
      "no_natural_setup":"No repair required; the strategy evaluated normally and found no qualified setup.",
    }.get(reason,"Inspect the owning module and exact reason histogram before changing downstream gates.")
    if unsupported: recommendation="Quarantine unsupported Kraken symbols from dynamic batches, then re-run ingress. "+recommendation
    stages=[
      {"stage":"FOCUS_ADMITTED","input":admitted,"pass":admitted},
      {"stage":"ROAMING_SCAN","input":admitted,"pass":roaming},
      {"stage":"MARKET_READY","input":roaming,"pass":market},
      {"stage":"HISTORY_READY","input":market,"pass":history},
      {"stage":"STRATEGY_EVALUATED","input":history,"pass":evaluated},
      {"stage":"WATCH","input":evaluated,"pass":watch},
      {"stage":"FIRE_OR_BEYOND","input":watch,"pass":fire},
    ]
    return {
      "version":MAINTENANCE_VERSION,"healthy_profile_version":HEALTHY_PROFILE_VERSION,
      "status":status,"severity":"HIGH" if status in {"BLOCKED","FAULT"} else ("MEDIUM" if status=="DEGRADED" else "NONE"),
      "first_causal_edge":edge,"owner":owner,"expected":"Every active candidate has an explainable PASS/WAIT/KILL destination.",
      "observed":observed,"affected_count":affected,"primary_reason":reason,
      "secondary_reasons":[{"reason":k,"count":v} for k,v in reasons.most_common(8) if k!=reason],
      "downstream_effects":downstream,"not_root_causes":not_root,"confidence":confidence,
      "unsupported_symbols":list(unsupported),"auto_fix_available":bool(unsupported),"recommended_action":recommendation,
      "stages":stages,
      "healthy_system":{"unexplained_asset_loss":0,"orphan_reservations":0,"impossible_state_transitions":0,"live_orders":0,"zero_trades_may_be_healthy":True,"zero_evaluations_with_admitted_assets_is_unhealthy":True},
      "paper_only":PAPER_ONLY,"live_blocked":LIVE_BLOCKED,
    }

async def load_controls()->dict[str,bool]:
    store=VNextStore()
    async with open_vnext_engine() as engine:
      async with engine.connect() as conn:
        def read(c):
          t=store.tables["maintenance_controls"]; saved={str(r["control_key"]):bool(r["enabled"]) for r in c.execute(sa.select(t)).mappings()}
          return {k:saved.get(k,v) for k,v in CONTROL_DEFAULTS.items()}
        return await conn.run_sync(read)

async def set_control(*,key:str,enabled:bool,actor:str)->dict[str,bool]:
    if key not in CONTROL_DEFAULTS: raise KeyError(key)
    now=datetime.now(UTC); store=VNextStore()
    async with open_vnext_engine() as engine:
      async with engine.begin() as conn:
        def write(c):
          t=store.tables["maintenance_controls"]; row=c.execute(sa.select(t).where(t.c.control_key==key).with_for_update()).mappings().first()
          if row is None: c.execute(t.insert().values(control_key=key,enabled=bool(enabled),updated_at_utc=now,updated_by=actor,row_version=1))
          else: c.execute(t.update().where(t.c.control_key==key).values(enabled=bool(enabled),updated_at_utc=now,updated_by=actor,row_version=int(row["row_version"])+1))
        await conn.run_sync(write)
    return await load_controls()

async def record_incident(d:Mapping[str,object],repair:Mapping[str,object])->None:
    if d.get("status")=="CLEAR": return
    controls=await load_controls()
    if not controls.get("incident_history_enabled",True): return
    now=datetime.now(UTC); fp_raw=f"{d.get('first_causal_edge')}|{d.get('primary_reason')}|{d.get('owner')}"; fp=hashlib.sha256(fp_raw.encode()).hexdigest(); iid="maint-"+fp[:20]; store=VNextStore()
    async with open_vnext_engine() as engine:
      async with engine.begin() as conn:
        def write(c):
          t=store.tables["maintenance_incidents"]; row=c.execute(sa.select(t).where(t.c.fingerprint==fp).with_for_update()).mappings().first()
          vals=dict(status=str(d.get("status")),stage=str(d.get("first_causal_edge")),owner=str(d.get("owner")),reason=str(d.get("primary_reason")),affected_count=int(d.get("affected_count") or 0),diagnosis=dict(d),repair=dict(repair),last_seen_at_utc=now,resolved=False)
          if row is None: c.execute(t.insert().values(incident_id=iid,fingerprint=fp,first_seen_at_utc=now,recurrence_count=1,**vals))
          else: c.execute(t.update().where(t.c.fingerprint==fp).values(recurrence_count=int(row["recurrence_count"])+1,**vals))
        await conn.run_sync(write)

async def incident_history(limit:int=20)->list[dict[str,object]]:
    store=VNextStore()
    async with open_vnext_engine() as engine:
      async with engine.connect() as conn:
        def read(c):
          t=store.tables["maintenance_incidents"]; rows=c.execute(sa.select(t).order_by(t.c.last_seen_at_utc.desc()).limit(max(1,min(limit,100)))).mappings()
          return [{**dict(r),"first_seen_at_utc":r["first_seen_at_utc"].isoformat(),"last_seen_at_utc":r["last_seen_at_utc"].isoformat()} for r in rows]
        return await conn.run_sync(read)

def safe_repair(d:Mapping[str,object],controls:Mapping[str,bool],*,force:bool=False)->dict[str,object]:
    out={"attempted":False,"level":None,"action":None,"result":"NO_ACTION","rollback":"not_required"}
    if not force and not controls.get("auto_repair_enabled",False): return out
    if not controls.get("level1_safe_repair_enabled",True) or not controls.get("unsupported_symbol_quarantine_enabled",True): return out
    symbols=tuple(str(x) for x in d.get("unsupported_symbols") or [])
    if not symbols: return out
    before=list(maintenance_quarantine_snapshot()); after=list(maintenance_quarantine_symbols(symbols))
    return {"attempted":True,"level":1,"action":"quarantine_unsupported_kraken_symbols","symbols":list(symbols),"before":before,"after":after,"result":"REPAIR_APPLIED","rollback":"not_required"}

StatusProvider=Callable[[],Mapping[str,object]|Awaitable[Mapping[str,object]]]

class PipelineMaintenanceSupervisor:
    def __init__(self,*,ingress_provider:StatusProvider,discovery_provider:StatusProvider,strategy_provider:StatusProvider,interval_seconds:float=15.0):
      self._ingress=ingress_provider; self._discovery=discovery_provider; self._strategy=strategy_provider; self._interval=float(interval_seconds); self._task=None; self._stop: asyncio.Event | None=None; self._cycles=0; self._started=None; self._finished=None; self._error=None; self._result=None
    @property
    def running(self): return self._task is not None and not self._task.done()
    async def _value(self,p):
      x=p(); return await x if inspect.isawaitable(x) else x
    async def run_once(self,*,force_repair:bool=False):
      controls=await load_controls()
      if not controls.get("master_enabled",True): return {"version":MAINTENANCE_VERSION,"status":"DISABLED","controls":controls,"paper_only":True,"live_blocked":True}
      if not controls.get("diagnostics_enabled",True): return {"version":MAINTENANCE_VERSION,"status":"PAUSED","controls":controls,"paper_only":True,"live_blocked":True}
      d=diagnose_pipeline(ingress=await self._value(self._ingress),discovery=await self._value(self._discovery),strategy=await self._value(self._strategy))
      repair=safe_repair(d,controls,force=force_repair); d["controls"]=controls; d["repair"]=repair; d["quarantined_symbols"]=list(maintenance_quarantine_snapshot()); await record_incident(d,repair); return d
    def status(self): return MaintenanceStatus(True,self.running,PAPER_ONLY,LIVE_BLOCKED,self._cycles,self._interval,None if self._started is None else self._started.isoformat(),None if self._finished is None else self._finished.isoformat(),self._error,self._result)
    async def start(self):
      if self.running:return
      if not PAPER_ONLY or not LIVE_BLOCKED: raise RuntimeError("Maintenance requires PAPER_ONLY/LIVE_BLOCKED")
      self._stop=asyncio.Event(); self._task=asyncio.create_task(self._run(),name="aether-vnext-maintenance")
    async def stop(self):
      if self._stop is not None: self._stop.set()
      if self._task is None:return
      self._task.cancel()
      try: await self._task
      except asyncio.CancelledError: pass
      self._task=None
    async def _run(self):
      stop=self._stop
      if stop is None: return
      while not stop.is_set():
        self._started=datetime.now(UTC)
        try: self._result=await self.run_once(); self._error=None; self._cycles+=1
        except asyncio.CancelledError: raise
        except Exception as exc: self._error=f"{type(exc).__name__}:{exc}"
        self._finished=datetime.now(UTC)
        try: await asyncio.wait_for(stop.wait(),timeout=self._interval)
        except TimeoutError: continue

def configured_maintenance_interval_seconds()->float:
    v=float(os.getenv("AETHER_VNEXT_MAINTENANCE_INTERVAL_SECONDS","15"))
    if v<5 or v>300: raise ValueError("maintenance interval must be 5..300")
    return v

def status_payload(status:MaintenanceStatus)->dict[str,object]: return asdict(status)
