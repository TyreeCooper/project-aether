"""FastAPI lifecycle and operator controls for AETHER Pipeline Maintenance."""
from __future__ import annotations
import asyncio, hmac, os
from datetime import datetime, timezone
from time import perf_counter
from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel
from app.vnext_discovery import current_discovery_status
from app.vnext_ingress import configured_vnext_ingress_status
from app.vnext_strategy import configured_vnext_strategy_status
from app.vnext_tape import configured_vnext_tape_status
from aether_vnext.maintenance_agent import (
    CONTROL_DEFAULTS,
    CONTROL_LABELS,
    MaintenanceIdleTimeout,
    PipelineMaintenanceSupervisor,
    configured_maintenance_cycle_timeout_seconds,
    configured_maintenance_idle_timeout_seconds,
    configured_maintenance_interval_seconds,
    configured_maintenance_repair_timeout_seconds,
    incident_history,
    load_controls,
    set_control,
    status_payload,
)

_supervisor:PipelineMaintenanceSupervisor|None=None
_last_manual_repair: dict[str, object] | None = None
# Worker-local authority: every process boot starts maintenance OFF/IDLE even if a
# prior worker persisted master_enabled=true. Explicit operator action re-arms it.
_maintenance_armed = False
class ControlBody(BaseModel): enabled:bool

def _operator(token:str|None)->str:
    expected=os.getenv("AETHER_OPERATOR_TOKEN","").strip()
    if not expected: raise HTTPException(status_code=503,detail="operator authentication not configured")
    if not token or not hmac.compare_digest(token,expected): raise HTTPException(status_code=401,detail="operator authentication required")
    return "operator"

def _instance():
    global _supervisor
    if _supervisor is None:
      _supervisor=PipelineMaintenanceSupervisor(
          ingress_provider=configured_vnext_ingress_status,
          discovery_provider=current_discovery_status,
          strategy_provider=configured_vnext_strategy_status,
          tape_provider=configured_vnext_tape_status,
          interval_seconds=configured_maintenance_interval_seconds(),
          idle_timeout_seconds=configured_maintenance_idle_timeout_seconds(),
          cycle_timeout_seconds=configured_maintenance_cycle_timeout_seconds(),
      )
    return _supervisor

def configured_maintenance_enabled() -> bool:
    return os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "sandbox"


async def start_configured_vnext_maintenance():
    # Startup is deliberately inert. Maintenance must not compete with the initial
    # market-data/runtime warm-up or diagnose partial boot state as a fault.
    global _maintenance_armed
    _maintenance_armed = False


async def stop_configured_vnext_maintenance():
    global _maintenance_armed
    _maintenance_armed = False
    if _supervisor is not None:
        await _supervisor.stop()
def configured_vnext_maintenance_status():
    if _supervisor is None:
      return {
          "enabled":True,
          "running":False,
          "paper_only":True,
          "live_blocked":True,
          "cycle_count":0,
          "interval_seconds":configured_maintenance_interval_seconds(),
          "idle_timeout_seconds":configured_maintenance_idle_timeout_seconds(),
          "cycle_timeout_seconds":configured_maintenance_cycle_timeout_seconds(),
          "last_cycle_started_at_utc":None,
          "last_cycle_finished_at_utc":None,
          "last_error":None,
          "last_result":None,
          "operation_kind":None,
          "operation_phase":None,
          "operation_started_at_utc":None,
          "operation_last_progress_at_utc":None,
          "last_timeout_phase":None,
          "healthy_baseline_established":False,
      }
    return status_payload(_supervisor.status())

def mount_vnext_maintenance(app:FastAPI)->None:
    router=APIRouter()
    @router.get("/api/v1/vnext/maintenance")
    async def read():
      payload=configured_vnext_maintenance_status()
      idle_timeout=configured_maintenance_idle_timeout_seconds()
      try:
          controls=await asyncio.wait_for(
              load_controls(),
              timeout=idle_timeout,
          )
          # The persisted preference never auto-arms a newly booted worker.
          controls["master_enabled"]=bool(_maintenance_armed)
          payload["controls"]=controls
      except TimeoutError:
          payload["controls"]=dict(CONTROL_DEFAULTS)
          payload["controls"]["master_enabled"]=bool(_maintenance_armed)
          payload["control_read_warning"]="maintenance_control_store_timeout"
      payload["control_labels"]=CONTROL_LABELS
      payload["control_defaults"]=CONTROL_DEFAULTS
      try:
          payload["incidents"]=await asyncio.wait_for(
              incident_history(20),
              timeout=idle_timeout,
          )
      except TimeoutError:
          payload["incidents"]=[]
          payload["incident_read_warning"]="maintenance_incident_store_timeout"
      payload["repair_timeout_seconds"]=configured_maintenance_repair_timeout_seconds()
      payload["last_manual_repair"]=_last_manual_repair
      return payload
    @router.post("/api/v1/vnext/maintenance/controls/{control_key}")
    async def control(control_key:str,body:ControlBody,x_operator_token:str|None=Header(default=None)):
      global _maintenance_armed
      actor=_operator(x_operator_token)
      try: controls=await set_control(key=control_key,enabled=body.enabled,actor=actor)
      except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
      if control_key == "master_enabled":
          _maintenance_armed=bool(body.enabled)
          if _maintenance_armed:
              await _instance().start()
          else:
              await stop_configured_vnext_maintenance()
          controls["master_enabled"]=_maintenance_armed
      return {"ok":True,"controls":controls}
    @router.post("/api/v1/vnext/maintenance/repair")
    async def repair(x_operator_token:str|None=Header(default=None)):
      global _last_manual_repair
      _operator(x_operator_token)
      if not _maintenance_armed:
          raise HTTPException(
              status_code=409,
              detail="Maintenance is IDLE. Enable Maintenance Agent before repair.",
          )
      started_at = datetime.now(timezone.utc)
      started = perf_counter()
      timeout_seconds = configured_maintenance_repair_timeout_seconds()
      try:
          result = await asyncio.wait_for(
              _instance().run_once(force_repair=True),
              timeout=timeout_seconds,
          )
      except MaintenanceIdleTimeout as exc:
          completed_at = datetime.now(timezone.utc)
          _last_manual_repair = {
              "started_at_utc": started_at.isoformat(),
              "completed_at_utc": completed_at.isoformat(),
              "duration_ms": round((perf_counter() - started) * 1000, 1),
              "outcome": "TIMED_OUT_IDLE",
              "action": None,
              "attempted": True,
              "status": "ENDED",
              "primary_reason": f"idle_timeout:{exc.phase}",
              "timeout_seconds": exc.timeout_seconds,
          }
          raise HTTPException(
              status_code=504,
              detail=(
                  "Safe repair ended because no progress completed before "
                  f"the {exc.timeout_seconds:g}s idle deadline "
                  f"during {exc.phase}."
              ),
          ) from exc
      except TimeoutError as exc:
          completed_at = datetime.now(timezone.utc)
          _last_manual_repair = {
              "started_at_utc": started_at.isoformat(),
              "completed_at_utc": completed_at.isoformat(),
              "duration_ms": round((perf_counter() - started) * 1000, 1),
              "outcome": "TIMED_OUT_TOTAL",
              "action": None,
              "attempted": True,
              "status": "ENDED",
              "primary_reason": "repair_total_timeout",
              "timeout_seconds": timeout_seconds,
          }
          raise HTTPException(
              status_code=504,
              detail=(
                  "Safe repair ended at the bounded "
                  f"{timeout_seconds:g}s repair deadline."
              ),
          ) from exc

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
          "maintenance_mode": result.get("maintenance_mode"),
          "healthy_baseline_established": result.get(
              "healthy_baseline_established"
          ),
          "primary_reason": result.get("primary_reason"),
          "timeout_seconds": timeout_seconds,
      }
      return {"ok":True,"result":result,"operation":_last_manual_repair}
    app.include_router(router)
