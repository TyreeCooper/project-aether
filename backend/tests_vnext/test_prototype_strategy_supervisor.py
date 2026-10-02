from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from aether_vnext.dynamic_products import project_kraken_spot_product

import pytest

from aether_vnext.prototype_strategy_supervisor import (
    PrototypeStrategySupervisor,
    _coinbase_warmup_cached,
    _kraken_history_cached,
    _partition_observations_for_decision_time,
    _current_dynamic_kraken_products,
    _entry_focus_block,
    _dynamic_flow_telemetry,
    _focus_priority_asset_ids,
    _ordered_dynamic_strategy_work,
    _sync_dynamic_kraken_products,
    configured_dynamic_strategy_scan_batch_size,
    configured_strategy_enabled,
    configured_strategy_interval_seconds,
    validate_configured_strategy_environment,
)


def test_strategy_enabled_by_default_in_sandbox(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("AETHER_VNEXT_DATABASE_URL", "postgresql://user:pass@example.invalid/aether")
    monkeypatch.delenv("AETHER_VNEXT_SANDBOX_TRADING_ENABLED", raising=False)
    assert configured_strategy_enabled() is True
    validate_configured_strategy_environment()


def test_enabled_strategy_refuses_non_sandbox(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_SANDBOX_TRADING_ENABLED", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="sandbox"):
        validate_configured_strategy_environment()


def test_strategy_interval_has_hard_lower_bound(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_SANDBOX_TRADING_INTERVAL_SECONDS", "4")
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



def test_remote_exchange_clock_skew_does_not_abort_strategy_cycle() -> None:
    decision_at = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
    accepted, rejected, exchange_ahead = _partition_observations_for_decision_time(
        {
            "kraken:solusd": SimpleNamespace(
                received_ts=datetime(2026, 10, 1, 19, 59, 59, tzinfo=timezone.utc),
                exchange_ts=datetime(2026, 10, 1, 20, 0, 1, tzinfo=timezone.utc),
            ),
            "kraken:adausd": SimpleNamespace(
                received_ts=datetime(2026, 10, 1, 20, 0, 1, tzinfo=timezone.utc),
                exchange_ts=datetime(2026, 10, 1, 19, 59, 59, tzinfo=timezone.utc),
            ),
        },
        decision_at_utc=decision_at,
    )

    assert tuple(accepted) == ("kraken:solusd",)
    assert rejected == {
        "kraken:adausd": "received_timestamp_after_decision_time",
    }
    assert exchange_ahead == ("kraken:solusd",)


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



def _dynamic_product(symbol: str):
    base = symbol.split("/", 1)[0]
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": symbol,
            "execution_symbol": symbol.replace("/", ""),
            "asset_class": "spot_crypto",
            "base_currency": base,
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.01,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15000,
    )
    assert projection.product is not None
    return projection.product


def test_dynamic_strategy_scan_batch_size_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_DYNAMIC_STRATEGY_SCAN_BATCH_SIZE", "4")
    assert configured_dynamic_strategy_scan_batch_size() == 4
    monkeypatch.setenv("AETHER_VNEXT_DYNAMIC_STRATEGY_SCAN_BATCH_SIZE", "21")
    with pytest.raises(ValueError, match="between 1 and 20"):
        configured_dynamic_strategy_scan_batch_size()


def test_current_dynamic_products_are_not_hard_gated_by_top100_focus() -> None:
    sol = _dynamic_product("SOL/USD")
    ada = _dynamic_product("ADA/USD")
    states = ({"product": sol}, {"product": ada})
    focus = {
        "providers": {
            "Kraken": {
                "top100": [
                    {"execution_symbol": "SOLUSD"},
                ]
            }
        }
    }
    rows = _current_dynamic_kraken_products(
        states,
        focus_snapshot=focus,
    )
    assert tuple(row.asset_id for row in rows) == (
        "kraken:adausd",
        "kraken:solusd",
    )
    assert _focus_priority_asset_ids(rows, focus_snapshot=focus) == (
        "kraken:solusd",
    )


def test_dynamic_strategy_work_orders_full_universe_open_first() -> None:
    products = tuple(_dynamic_product(symbol) for symbol in ("ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "SOL/USD"))
    selected = _ordered_dynamic_strategy_work(
        products,
        priority_asset_ids=("kraken:solusd",),
        attention_asset_ids=("kraken:adausd",),
    )
    assert selected[0].asset_id == "kraken:solusd"
    assert selected[1].asset_id == "kraken:adausd"
    assert len(selected) == len(products)
    assert {row.asset_id for row in selected} == {row.asset_id for row in products}


def test_dynamic_strategy_work_never_drops_assets_for_worker_limit() -> None:
    products = tuple(_dynamic_product(symbol) for symbol in ("ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "SOL/USD"))
    selected = _ordered_dynamic_strategy_work(
        products,
        priority_asset_ids=("kraken:adausd", "kraken:avaxusd", "kraken:dotusd"),
    )
    assert len(selected) == 5
    assert tuple(row.asset_id for row in selected[:3]) == ("kraken:adausd", "kraken:avaxusd", "kraken:dotusd")


def test_coinbase_warmup_cache_requires_full_reference_window() -> None:
    rows = tuple(
        SimpleNamespace(source_id="coinbase_exchange_public_candles")
        for _ in range(2200)
    )
    assert _coinbase_warmup_cached(rows) is True
    assert _coinbase_warmup_cached(rows[:-1]) is False
    mixed = (
        *rows[:-1],
        SimpleNamespace(source_id="kraken_public_rest_ohlc"),
    )
    assert _coinbase_warmup_cached(mixed) is False


def test_kraken_history_cache_tracks_completed_bar_boundaries() -> None:
    as_of = datetime(2026, 10, 2, 19, 30, tzinfo=timezone.utc)
    hourly = (
        SimpleNamespace(
            source_id="cryptocompare_kraken_histohour",
            bucket_close_utc=datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc),
        ),
    )
    daily = (
        SimpleNamespace(
            source_id="kraken_public_rest_ohlc",
            bucket_close_utc=datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc),
        ),
    )
    assert _kraken_history_cached(hourly, daily, as_of_utc=as_of) is True

    stale_hourly = (
        SimpleNamespace(
            source_id="cryptocompare_kraken_histohour",
            bucket_close_utc=datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc),
        ),
    )
    assert _kraken_history_cached(stale_hourly, daily, as_of_utc=as_of) is False


def test_dynamic_strategy_attention_priority_never_starves_background_catalog() -> None:
    products = tuple(_dynamic_product(symbol) for symbol in ("ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "SOL/USD", "XRP/USD"))
    selected = _ordered_dynamic_strategy_work(
        products,
        attention_asset_ids=("kraken:solusd", "kraken:adausd", "kraken:avaxusd", "kraken:dotusd"),
    )
    assert len(selected) == len(products)
    assert {row.asset_id for row in selected} == {row.asset_id for row in products}


def test_dynamic_strategy_scan_default_is_twelve(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_VNEXT_DYNAMIC_STRATEGY_SCAN_BATCH_SIZE", raising=False)
    assert configured_dynamic_strategy_scan_batch_size() == 12


def test_dynamic_flow_telemetry_keeps_waiting_assets_owned() -> None:
    products = tuple(_dynamic_product(symbol) for symbol in ("ADA/USD", "DOT/USD", "SOL/USD"))
    active = products[:2]
    flow = _dynamic_flow_telemetry(
        products, active,
        as_of_utc=datetime(2026, 10, 2, 19, 30, tzinfo=timezone.utc),
        concurrency=2,
    )
    assert flow["eligible_asset_count"] == 3
    assert flow["active_worker_count"] == 2
    assert flow["waiting_asset_count"] == 1
    assert flow["waiting_dependency"] == "worker_capacity"
    assert flow["wake_condition"] == "worker_slot_available"
    assert flow["assets_dropped"] == 0
    assert flow["priority_is_allowlist"] is False
