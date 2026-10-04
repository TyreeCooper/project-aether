from __future__ import annotations
from pathlib import Path
import pytest
import aether_vnext.maintenance_agent as maintenance_agent
from aether_vnext.maintenance_agent import (
    CONTROL_DEFAULTS,
    MaintenanceIdleTimeout,
    PipelineMaintenanceSupervisor,
    configured_maintenance_idle_timeout_seconds,
    diagnose_pipeline,
)

def base(): return {"enabled":True,"running":True,"last_error":None,"paper_only":True,"live_blocked":True}

def test_first_market_clog_is_causal_and_downstream_is_suppressed():
    ingress={**base(),"last_result":{"asset_results":[{"asset_id":"btc","executable":False,"reason":"quote_stale"},{"asset_id":"eth","executable":False,"reason":"quote_stale"}],"batch_errors":[]}}
    discovery={**base(),"last_result":{"focus_admitted_count":100,"providers":{}}}
    strategy={**base(),"last_result":{"pipeline":{"roaming_batch":4,"market_ready":0,"history_ready":0,"strategy_evaluated":0,"watch":0,"fire_or_beyond":0}}}
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["status"]=="BLOCKED"; assert d["first_causal_edge"]=="ROAMING_SCAN→MARKET_READY"; assert d["primary_reason"]=="quote_stale"; assert "Scout" in d["not_root_causes"]

def test_zero_watch_can_be_healthy():
    ingress={**base(),"last_result":{"asset_results":[]}}
    discovery={**base(),"last_result":{"focus_admitted_count":10,"providers":{}}}
    strategy={**base(),"last_result":{"pipeline":{"roaming_batch":4,"market_ready":4,"history_ready":4,"strategy_evaluated":4,"watch":0,"fire_or_beyond":0,"evaluation_error":0}}}
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["status"]=="CLEAR"; assert d["primary_reason"]=="no_natural_setup"

def test_unsupported_symbol_exposes_safe_repair_after_runtime_baseline():
    completed = {
        "cycle_count": 1,
        "last_cycle_finished_at_utc": "2026-10-02T17:00:00+00:00",
    }
    ingress={
        **base(),
        **completed,
        "last_result":{
            "asset_results":[],
            "batch_errors":[{"error":"RuntimeError:Currency pair not supported XDG/USD"}],
        },
    }
    discovery={
        **base(),
        **completed,
        "last_result":{"focus_admitted_count":10,"providers":{}},
    }
    strategy={
        **base(),
        **completed,
        "last_result":{
            "dynamic_product_registry":{
                "status":"synced",
                "received":1,
                "persisted":1,
            },
            "dynamic_roam":{"available":1},
            "pipeline":{
                "dynamic_kraken_available":1,
                "roaming_batch":1,
                "market_ready":0,
                "history_ready":0,
                "strategy_evaluated":0,
                "watch":0,
                "fire_or_beyond":0,
            },
        },
    }
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["status"]=="BLOCKED"
    assert d["first_causal_edge"]=="ROAMING_SCAN→MARKET_READY"
    assert d["unsupported_symbols"]==["XDG/USD"]
    assert d["auto_fix_available"] is True

def test_revision_0035_is_maintenance_schema():
    backend=Path(__file__).resolve().parents[1]
    migration=(backend/"alembic"/"versions"/"0035_aether_vnext_pipeline_maintenance.py").read_text()
    assert 'revision: str = "0035"' in migration
    assert 'down_revision: Union[str, None] = "0034"' in migration
    assert "maintenance_controls" in migration and "maintenance_incidents" in migration


def test_maintenance_defaults_to_operator_armed_off() -> None:
    assert CONTROL_DEFAULTS["master_enabled"] is False
    assert CONTROL_DEFAULTS["auto_repair_enabled"] is False


def test_maintenance_runtime_only_starts_in_sandbox(monkeypatch) -> None:
    from app.vnext_maintenance import configured_maintenance_enabled

    monkeypatch.delenv("AETHER_VNEXT_ENVIRONMENT", raising=False)
    assert configured_maintenance_enabled() is False
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    assert configured_maintenance_enabled() is True


def test_newer_discovery_snapshot_is_busy_not_false_blocked() -> None:
    ingress={
        **base(),
        "cycle_count":2,
        "last_cycle_finished_at_utc":"2026-10-02T17:00:00+00:00",
        "last_result":{"asset_results":[]},
    }
    discovery={
        **base(),
        "cycle_count":2,
        "last_cycle_finished_at_utc":"2026-10-02T17:00:20+00:00",
        "last_result":{"focus_admitted_count":279,"providers":{"Kraken":{"eligible_count":120}}},
    }
    strategy={
        **base(),
        "cycle_count":1,
        "last_cycle_finished_at_utc":"2026-10-02T17:00:10+00:00",
        "last_result":{"pipeline":{"roaming_batch":0}},
    }
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["status"]=="BUSY"
    assert d["primary_reason"]=="awaiting_strategy_sync"
    assert d["maintenance_mode"]=="CATCHING_UP"


def test_healthy_pipeline_is_the_only_maintaining_mode() -> None:
    ingress={**base(),"last_result":{"asset_results":[]}}
    discovery={**base(),"last_result":{"focus_admitted_count":10,"providers":{}}}
    strategy={**base(),"last_result":{"pipeline":{"roaming_batch":4,"market_ready":4,"history_ready":4,"strategy_evaluated":4,"watch":1,"fire_or_beyond":0}}}
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["status"]=="CLEAR"
    assert d["healthy_now"] is True
    assert d["maintenance_mode"]=="MAINTAINING"


def test_runtime_binding_diagnosis_uses_runtime_catalog_not_all_provider_focus() -> None:
    ingress={**base(),"last_result":{"asset_results":[]}}
    discovery={
        **base(),
        "last_result":{
            "focus_admitted_count":279,
            "providers":{"Kraken":{"eligible_count":120}},
        },
    }
    strategy={
        **base(),
        "last_result":{
            "dynamic_product_registry":{"status":"synced","received":120,"persisted":118},
            "dynamic_roam":{"available":118},
            "pipeline":{"roaming_batch":20,"market_ready":20,"history_ready":20,"strategy_evaluated":20,"watch":0,"fire_or_beyond":0,"evaluation_error":0},
        },
    }
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["status"]=="CLEAR"
    roaming=next(row for row in d["stages"] if row["stage"]=="ROAMING_SCAN")
    assert roaming["input"]==118
    assert roaming["pass"]==20


def test_maintenance_idle_timeout_has_bounded_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_MAINTENANCE_IDLE_TIMEOUT_SECONDS","15")
    assert configured_maintenance_idle_timeout_seconds()==15
    monkeypatch.setenv("AETHER_VNEXT_MAINTENANCE_IDLE_TIMEOUT_SECONDS","2")
    with pytest.raises(ValueError,match="3..60"):
        configured_maintenance_idle_timeout_seconds()


async def _never_finishes():
    import asyncio
    await asyncio.sleep(1)
    return {}


def test_maintenance_agent_exposes_idle_timeout_type() -> None:
    exc=MaintenanceIdleTimeout("read_strategy",15)
    assert exc.phase=="read_strategy"
    assert "idle deadline" in str(exc)


def test_maintenance_supervisor_has_hard_cycle_watchdog_in_source() -> None:
    source=Path(__file__).resolve().parents[1].joinpath("aether_vnext","maintenance_agent.py").read_text()
    assert "asyncio.wait_for(" in source
    assert "maintenance_cycle_timeout" in source
    assert "MaintenanceIdleTimeout" in source
    assert "healthy_baseline_established" in source


def test_clear_diagnosis_keeps_maintenance_semantics() -> None:
    result = diagnose_pipeline(
        ingress={"enabled": True, "running": True, "cycle_count": 2, "last_result": {"asset_results": []}},
        discovery={"enabled": True, "running": True, "cycle_count": 2, "last_result": {}},
        strategy={"enabled": True, "running": True, "cycle_count": 2, "last_result": {"pipeline": {"strategy_evaluated": 1, "watch": 0}}},
    )
    assert result["status"] == "CLEAR"
    assert result["maintenance_mode"] == "MAINTAINING"
    assert result["primary_reason"] == "no_natural_setup"


@pytest.mark.asyncio
async def test_background_maintenance_uses_safe_defaults_when_control_store_stalls(
    monkeypatch,
) -> None:
    import asyncio

    async def stalled_controls():
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(
        maintenance_agent,
        "load_controls",
        stalled_controls,
    )
    status = {
        "enabled": True,
        "running": True,
        "last_error": None,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 0,
        "last_result": {},
    }
    supervisor = PipelineMaintenanceSupervisor(
        ingress_provider=lambda: status,
        discovery_provider=lambda: status,
        strategy_provider=lambda: status,
        interval_seconds=15,
        idle_timeout_seconds=0.01,
        cycle_timeout_seconds=1,
    )

    result = await supervisor.run_once()

    # A control-store timeout now falls back to the startup-safe defaults. Since
    # master_enabled defaults OFF, the maintenance worker remains inert rather than
    # diagnosing a partially warmed runtime or attempting any repair.
    assert result["status"] == "DISABLED"
    assert result["maintenance_mode"] == "OFF"
    assert result["controls"]["master_enabled"] is False
    assert result["controls"]["auto_repair_enabled"] is False
    assert result["paper_only"] is True
    assert result["live_blocked"] is True
    assert supervisor.status().last_timeout_phase == "load_controls"


@pytest.mark.asyncio
async def test_manual_repair_fails_closed_when_control_store_stalls(
    monkeypatch,
) -> None:
    import asyncio

    async def stalled_controls():
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(
        maintenance_agent,
        "load_controls",
        stalled_controls,
    )
    status = {
        "enabled": True,
        "running": True,
        "last_error": None,
        "paper_only": True,
        "live_blocked": True,
        "cycle_count": 0,
        "last_result": {},
    }
    supervisor = PipelineMaintenanceSupervisor(
        ingress_provider=lambda: status,
        discovery_provider=lambda: status,
        strategy_provider=lambda: status,
        idle_timeout_seconds=0.01,
        cycle_timeout_seconds=1,
    )

    with pytest.raises(MaintenanceIdleTimeout):
        await supervisor.run_once(force_repair=True)


def test_tape_is_a_first_class_maintenance_dependency_when_supplied():
    status = {
        "enabled": True,
        "running": True,
        "cycle_count": 1,
        "last_error": None,
        "last_result": {},
    }
    tape = {
        **status,
        "last_result": {
            "assets": [
                {"asset_id": "btc", "state": "DEGRADED"},
                {"asset_id": "eth", "state": "CONTESTED"},
            ]
        },
    }
    strategy = {
        **status,
        "last_result": {
            "pipeline": {
                "roaming_batch": 4,
                "market_ready": 4,
                "history_ready": 4,
                "strategy_evaluated": 4,
                "watch": 0,
                "fire_or_beyond": 0,
                "evaluation_error": 0,
            }
        },
    }
    diagnosis = diagnose_pipeline(
        ingress={**status, "last_result": {"asset_results": []}},
        discovery={**status, "last_result": {"focus_admitted_count": 10, "providers": {}}},
        strategy=strategy,
        tape=tape,
    )
    assert diagnosis["status"] == "DEGRADED"
    assert diagnosis["first_causal_edge"] == "TAPE→MARKET_READY"
    assert diagnosis["primary_reason"] == "tape_full_quorum_unavailable"
    assert diagnosis["tape_health"]["full"] == 0
    assert diagnosis["tape_health"]["contested"] == 1


@pytest.mark.asyncio
async def test_maintenance_supervisor_reads_tape_status(monkeypatch) -> None:
    async def controls():
        return {**dict(CONTROL_DEFAULTS), "master_enabled": True}
    monkeypatch.setattr(maintenance_agent, "load_controls", controls)

    async def close_incidents(_diagnosis):
        return None
    monkeypatch.setattr(
        maintenance_agent,
        "close_cleared_incidents",
        close_incidents,
    )

    base_status = {
        "enabled": True,
        "running": True,
        "cycle_count": 1,
        "last_error": None,
        "last_result": {},
    }
    tape_status = {
        **base_status,
        "last_result": {"assets": [{"asset_id": "btc", "state": "FULL"}]},
    }
    strategy_status = {
        **base_status,
        "last_result": {
            "pipeline": {
                "strategy_evaluated": 1,
                "watch": 0,
                "fire_or_beyond": 0,
            }
        },
    }
    supervisor = PipelineMaintenanceSupervisor(
        ingress_provider=lambda: {**base_status, "last_result": {"asset_results": []}},
        discovery_provider=lambda: {**base_status, "last_result": {}},
        strategy_provider=lambda: strategy_status,
        tape_provider=lambda: tape_status,
        idle_timeout_seconds=1,
        cycle_timeout_seconds=2,
    )
    result = await supervisor.run_once()
    assert result["tape_health"]["required"] is True
    assert result["tape_health"]["full"] == 1


@pytest.mark.asyncio
async def test_configured_maintenance_boot_is_idle(monkeypatch) -> None:
    import app.vnext_maintenance as api

    class FakeSupervisor:
        running = False
        async def start(self):
            raise AssertionError("startup must not arm maintenance")

    monkeypatch.setattr(api, "_supervisor", FakeSupervisor())
    monkeypatch.setattr(api, "_maintenance_armed", True)

    await api.start_configured_vnext_maintenance()

    assert api._maintenance_armed is False
