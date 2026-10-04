from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_exhaustion_is_asset_scoped_and_does_not_stop_strategy_supervisor() -> None:
    source = (
        ROOT / "backend" / "aether_vnext" / "prototype_strategy_supervisor.py"
    ).read_text(encoding="utf-8")
    assert '"stage": "HISTORY_SOURCE_UNAVAILABLE"' in source
    assert '"isolated_failure": True' in source
    assert "history_service_unavailable" in source
    assert "continue" in source


def test_market_fabric_price_authority_survives_reference_source_failover() -> None:
    fabric = (
        ROOT / "backend" / "aether_vnext" / "market_fabric_consumers.py"
    ).read_text(encoding="utf-8")
    pool = (
        ROOT / "backend" / "aether_vnext" / "prototype_history_source_pool.py"
    ).read_text(encoding="utf-8")
    assert "No consumer may replace an executable price" in fabric
    assert "never participates in Market Fabric price authority" in pool
    assert "never blended" in pool


def test_history_recovery_selects_one_source_instead_of_composite_bars() -> None:
    source = (
        ROOT / "backend" / "aether_vnext" / "prototype_strategy_supervisor.py"
    ).read_text(encoding="utf-8")
    assert "select_persisted_reference_history(" in source
    assert "minimum_bars=REFERENCE_MINIMUM_BARS" in source
