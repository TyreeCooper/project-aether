from __future__ import annotations
from pathlib import Path
from aether_vnext.maintenance_agent import diagnose_pipeline

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

def test_unsupported_symbol_exposes_safe_repair():
    ingress={**base(),"last_result":{"asset_results":[],"batch_errors":[{"error":"RuntimeError:Currency pair not supported XDG/USD"}]}}
    discovery={**base(),"last_result":{"focus_admitted_count":10,"providers":{}}}
    strategy={**base(),"last_result":{"pipeline":{"roaming_batch":0,"market_ready":0,"history_ready":0,"strategy_evaluated":0,"watch":0,"fire_or_beyond":0}}}
    d=diagnose_pipeline(ingress=ingress,discovery=discovery,strategy=strategy)
    assert d["unsupported_symbols"]==["XDG/USD"]; assert d["auto_fix_available"] is True

def test_revision_0035_is_maintenance_schema():
    backend=Path(__file__).resolve().parents[1]
    migration=(backend/"alembic"/"versions"/"0035_aether_vnext_pipeline_maintenance.py").read_text()
    assert 'revision: str = "0035"' in migration
    assert 'down_revision: Union[str, None] = "0034"' in migration
    assert "maintenance_controls" in migration and "maintenance_incidents" in migration


def test_maintenance_runtime_only_starts_in_sandbox(monkeypatch) -> None:
    from app.vnext_maintenance import configured_maintenance_enabled

    monkeypatch.delenv("AETHER_VNEXT_ENVIRONMENT", raising=False)
    assert configured_maintenance_enabled() is False
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    assert configured_maintenance_enabled() is True
