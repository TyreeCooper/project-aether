from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_app_lifespan_starts_only_canonical_market_truth_market_authority() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    start = main.index("async def lifespan")
    end = main.index("\n\napp = FastAPI", start)
    block = main[start:end]
    assert "await start_configured_market_truth_runtime()" in block
    assert "await start_configured_vnext_discovery()" in block
    assert "await start_configured_vnext_ingress()" not in block
    assert "await start_configured_vnext_tape()" not in block
    assert "await start_configured_vnext_strategy()" not in block


def test_health_declares_legacy_authority_quarantined() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '"ingress": "QUARANTINED"' in main
    assert '"tape": "QUARANTINED"' in main
    assert '"strategy": "QUARANTINED"' in main
    assert '"market_truth_architecture": market_truth.get("architecture")' in main


def test_activation_workflow_disables_legacy_market_authority() -> None:
    workflow = (ROOT / ".github" / "workflows" / "aether-vnext-activate-paper-prototype.yml").read_text(encoding="utf-8")
    assert "AETHER_VNEXT_KRAKEN_INGRESS_ENABLED=false" in workflow
    assert "AETHER_VNEXT_SANDBOX_TRADING_ENABLED=false" in workflow
    assert "AETHER_VNEXT_TAPE_ENABLED=false" in workflow
    assert "/tmp/market-fabric-first.json" in workflow
    assert 'fabric.get("architecture") == "AETHER_MARKET_TRUTH_V1"' in workflow
