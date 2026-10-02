"""FastAPI lifecycle and operator controls for AETHER Pipeline Maintenance."""
from __future__ import annotations
import hmac, os
from datetime import datetime, timezone
from time import perf_counter
from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel
from app.vnext_discovery import current_discovery_status
from app.vnext_ingress import configured_vnext_ingress_status
from app.vnext_strategy import configured_vnext_strategy_status
from aether_vnext.maintenance_agent import CONTROL_DEFAULTS, CONTROL_LABELS, PipelineMaintenanceSupervisor, configured_maintenance_interval_seconds, incident_history, load_controls, set_control, status_payload

_supervisor:PipelineMaintenanceSupervisor|None=None
_last_manual_repair: dict[str, object] | None = None
class ControlBody(BaseModel): enabled:bool

def _operator(token:str|None)->str:
    expected=os.getenv("AETHER_OPERATOR_TOKEN","").strip()
    if not expected: raise HTTPException(status_code=503,detail="operator authentication not configured")
    if not token or not hmac.compare_digest(token,expected): raise HTTPException(status_code=401,detail="operator authentication required")
    return "operator"

def _instance():
    global _supervisor
    if _supervisor is None:
      _supervisor=PipelineMaintenanceSupervisor(ingress_provider=configured_vnext_ingress_status,discovery_provider=current_discovery_status,strategy_provider=configured_vnext_strategy_status,interval_seconds=configured_maintenance_interval_seconds())
    return _supervisor

def configured_maintenance_enabled() -> bool:
    return os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "sandbox"


async def start_configured_vnext_maintenance():
    if configured_maintenance_enabled():
        await _instance().start()


async def stop_configured_vnext_maintenance():
    if _supervisor is not None:
        await _supervisor.stop()
def configured_vnext_maintenance_status():
    if _supervisor is None: return {"enabled":True,"running":False,"paper_only":True,"live_blocked":True,"cycle_count":0,"interval_seconds":configured_maintenance_interval_seconds(),"last_cycle_started_at_utc":None,"last_cycle_finished_at_utc":None,"last_error":None,"last_result":None}
    return status_payload(_supervisor.status())

def mount_vnext_maintenance(app:FastAPI)->None:
    router=APIRouter()
    @router.get("/api/v1/vnext/maintenance")
    async def read():
      payload=configured_vnext_maintenance_status(); payload["controls"]=await load_controls(); payload["control_labels"]=CONTROL_LABELS; payload["control_defaults"]=CONTROL_DEFAULTS; payload["incidents"]=await incident_history(20); payload["last_manual_repair"]=_last_manual_repair; return payload
    @router.post("/api/v1/vnext/maintenance/controls/{control_key}")
    async def control(control_key:str,body:ControlBody,x_operator_token:str|None=Header(default=None)):
      actor=_operator(x_operator_token)
      try: controls=await set_control(key=control_key,enabled=body.enabled,actor=actor)
      except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
      return {"ok":True,"controls":controls}
    @router.post("/api/v1/vnext/maintenance/repair")
    async def repair(x_operator_token:str|None=Header(default=None)):
      global _last_manual_repair
      _operator(x_operator_token)
      started_at = datetime.now(timezone.utc)
      started = perf_counter()
      result = await _instance().run_once(force_repair=True)
      completed_at = datetime.now(timezone.utc)
      repair = result.get("repair") or {}
      outcome = str(repair.get("result") or "NO_ACTION")
      _last_manual_repair = {
          "started_at_utc": started_at.isoformat(),
          "completed_at_utc": completed_at.isoformat(),
          "duration_ms": round((perf_counter() - started) * 1000, 1),
          "outcome": outcome,
          "action": repair.get("action"),
          "attempted": bool(repair.get("attempted")),
          "status": result.get("status"),
          "primary_reason": result.get("primary_reason"),
      }
      return {"ok":True,"result":result,"operation":_last_manual_repair}
    app.include_router(router)
