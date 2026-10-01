from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aether_vnext.prototype_strategy_supervisor import (
    PrototypeStrategySupervisor,
    _entry_focus_block,
    _sync_dynamic_kraken_products,
    configured_strategy_enabled,
    configured_strategy_interval_seconds,
    validate_configured_strategy_environment,
)


def test_strategy_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_VNEXT_PROTOTYPE_TRADING_ENABLED", raising=False)
    assert configured_strategy_enabled() is False
    validate_configured_strategy_environment()


def test_enabled_strategy_refuses_non_burnin(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_PROTOTYPE_TRADING_ENABLED", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="only run in burnin"):
        validate_configured_strategy_environment()


def test_strategy_interval_has_hard_lower_bound(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_PROTOTYPE_TRADING_INTERVAL_SECONDS", "4")
    with pytest.raises(ValueError, match="must be >= 5"):
        configured_strategy_interval_seconds()


@pytest.mark.asyncio
async def test_strategy_supervisor_repeats_and_stops() -> None:
    calls = 0

    async def cycle() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "paper_only": True,
            "live_blocked": True,
            "phase18_evidence": False,
        }

    supervisor = PrototypeStrategySupervisor(
        cycle_runner=cycle,
        interval_seconds=0.01,
    )
    await supervisor.start()
    for _ in range(50):
        if calls >= 2:
            break
        await asyncio.sleep(0.01)
    status = supervisor.status()
    assert calls >= 2
    assert status.running is True
    assert status.cycle_count >= 2
    assert status.interval_seconds == 0.01
    assert status.last_error is None
    assert status.paper_only is True
    assert status.live_blocked is True
    await supervisor.stop()
    assert supervisor.status().running is False


@pytest.mark.asyncio
async def test_strategy_supervisor_records_fault_and_recovers() -> None:
    calls = 0

    async def cycle() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary source fault")
        return {"ok": True}

    supervisor = PrototypeStrategySupervisor(
        cycle_runner=cycle,
        interval_seconds=0.01,
    )
    await supervisor.start()
    for _ in range(50):
        if calls >= 2:
            break
        await asyncio.sleep(0.01)
    status = supervisor.status()
    assert calls >= 2
    assert status.running is True
    assert status.cycle_count >= 1
    assert status.last_error is None
    assert status.last_result == {"ok": True}
    await supervisor.stop()



def test_entry_focus_is_advisory_for_new_entries() -> None:
    focused = frozenset({"btc"})
    assert _entry_focus_block(
        asset_id="btc",
        focused_asset_ids=focused,
        assets_open_at_start=set(),
    ) is None
    assert _entry_focus_block(
        asset_id="eth",
        focused_asset_ids=focused,
        assets_open_at_start=set(),
    ) is None


def test_entry_focus_unavailable_does_not_block_commissioned_strategy() -> None:
    assert _entry_focus_block(
        asset_id="btc",
        focused_asset_ids=None,
        assets_open_at_start=set(),
    ) is None


def test_entry_focus_gate_never_blocks_management_of_open_trade() -> None:
    assert _entry_focus_block(
        asset_id="eth",
        focused_asset_ids=frozenset(),
        assets_open_at_start={"eth"},
    ) is None



def test_dynamic_kraken_registry_sync_uses_existing_provider_policy_without_guessing() -> None:
    class FakeStore:
        def __init__(self):
            self.rows = []

        def load_runtime_registry_binding(self, conn, *, asset_id):
            assert asset_id == "btc"
            return {
                "binding": SimpleNamespace(
                    primary_market_source_id="kraken_public",
                    stale_threshold_ms=15000,
                )
            }

        def upsert_dynamic_product_state(self, conn, product, **kwargs):
            self.rows.append((product, kwargs))
            return "hash"

    snapshot = {
        "providers": {
            "Kraken": {
                "top100": [
                    {
                        "symbol": "SOL/USD",
                        "execution_symbol": "SOLUSD",
                        "asset_class": "spot_crypto",
                        "base_currency": "SOL",
                        "quote_currency": "USD",
                        "quantity_step": 0.001,
                        "minimum_quantity": 0.02,
                        "minimum_notional": 0.5,
                        "tick_size": 0.0001,
                        "source": "kraken_public_rest",
                    },
                    {
                        "symbol": "ETH/EUR",
                        "execution_symbol": "ETHEUR",
                        "asset_class": "spot_crypto",
                        "base_currency": "ETH",
                        "quote_currency": "EUR",
                        "quantity_step": 0.001,
                        "minimum_quantity": 0.01,
                        "minimum_notional": 0.5,
                        "tick_size": 0.01,
                        "source": "kraken_public_rest",
                    },
                ]
            }
        }
    }
    store = FakeStore()
    result = _sync_dynamic_kraken_products(
        object(),
        store,
        focus_snapshot=snapshot,
        as_of_utc=datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc),
    )
    assert result["received"] == 2
    assert result["persisted"] == 1
    assert result["requirements"]["usd_settlement_route_required"] == 1
    assert store.rows[0][0].asset_id == "kraken:solusd"
    assert store.rows[0][0].stale_threshold_ms == 15000
