from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.kraken_ingress_supervisor import (
    KrakenIngressSupervisor,
    _chunks,
    _dynamic_kraken_symbol_map,
    _quote_telemetry,
    _quotes_by_asset,
    configured_dynamic_ingress_batch_size,
    configured_dynamic_ingress_worker_concurrency,
    configured_ingress_enabled,
    configured_ingress_interval_seconds,
    validate_configured_ingress_environment,
)
from aether_vnext.market_data import RawQuote


def test_ingress_is_enabled_by_default_in_sandbox(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("AETHER_VNEXT_DATABASE_URL", "postgresql://user:pass@example.invalid/aether")
    monkeypatch.delenv("AETHER_VNEXT_KRAKEN_INGRESS_ENABLED", raising=False)
    assert configured_ingress_enabled() is True
    validate_configured_ingress_environment()


def test_enabled_ingress_refuses_non_sandbox(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_INGRESS_ENABLED", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="sandbox"):
        validate_configured_ingress_environment()


def test_interval_has_hard_lower_bound(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_INGRESS_INTERVAL_SECONDS", "4")
    with pytest.raises(ValueError, match="must be >= 5"):
        configured_ingress_interval_seconds()


def test_quote_telemetry_exposes_real_kraken_quote_and_timestamp() -> None:
    ts = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
    quote = RawQuote(
        asset_id="btc",
        venue="kraken",
        source_id="kraken_public_ticker_v2",
        bid=65000.0,
        ask=65001.0,
        last=65000.5,
        mark=65000.5,
        exchange_ts=ts,
        received_ts=ts,
        adapter_version="test",
    )
    payload = _quote_telemetry(quote)
    assert payload["asset_id"] == "btc"
    assert payload["symbol"] == "BTC/USD"
    assert payload["mark"] == 65000.5
    assert payload["reference_ts_utc"] == ts.isoformat()
    assert payload["received_ts_utc"] == ts.isoformat()


def test_quotes_are_partitioned_once_by_canonical_asset_id() -> None:
    stamp = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)
    btc = RawQuote(
        asset_id="btc",
        venue="kraken",
        source_id="kraken_public_ticker_v2",
        bid=1.0,
        ask=2.0,
        last=1.5,
        mark=1.5,
        exchange_ts=stamp,
        received_ts=stamp,
        adapter_version="test",
    )
    eth = RawQuote(
        asset_id="eth",
        venue="kraken",
        source_id="kraken_public_ticker_v2",
        bid=3.0,
        ask=4.0,
        last=3.5,
        mark=3.5,
        exchange_ts=stamp,
        received_ts=stamp,
        adapter_version="test",
    )
    grouped = _quotes_by_asset((eth, btc))
    assert tuple(grouped) == ("btc", "eth")
    assert grouped["btc"] == (btc,)
    assert grouped["eth"] == (eth,)


@pytest.mark.asyncio
async def test_supervisor_runs_repeated_market_only_cycles_and_stops() -> None:
    calls = 0

    async def cycle() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "provider": "fake",
            "paper_only": True,
            "live_blocked": True,
        }

    supervisor = KrakenIngressSupervisor(
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
    assert isinstance(status.progress, dict)
    assert "cycle_state" in status.progress

    await supervisor.stop()
    assert supervisor.status().running is False


@pytest.mark.asyncio
async def test_supervisor_records_cycle_failure_without_dying() -> None:
    calls = 0

    async def cycle() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider unavailable")
        return {"ok": True}

    supervisor = KrakenIngressSupervisor(
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



def test_dynamic_ingress_batch_size_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_DYNAMIC_BATCH_SIZE", "20")
    assert configured_dynamic_ingress_batch_size() == 20
    assert _chunks(tuple(str(i) for i in range(45)), 20) == (
        tuple(str(i) for i in range(20)),
        tuple(str(i) for i in range(20, 40)),
        tuple(str(i) for i in range(40, 45)),
    )
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_DYNAMIC_BATCH_SIZE", "51")
    with pytest.raises(ValueError, match="between 1 and 50"):
        configured_dynamic_ingress_batch_size()


def test_dynamic_ingress_worker_concurrency_is_bounded(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_VNEXT_KRAKEN_INGRESS_WORKER_CONCURRENCY", raising=False)
    assert configured_dynamic_ingress_worker_concurrency() == 8
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_INGRESS_WORKER_CONCURRENCY", "12")
    assert configured_dynamic_ingress_worker_concurrency() == 12
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_INGRESS_WORKER_CONCURRENCY", "21")
    with pytest.raises(ValueError, match="between 1 and 20"):
        configured_dynamic_ingress_worker_concurrency()


def test_dynamic_kraken_symbol_map_uses_only_verified_usd_kraken_products() -> None:
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "execution_symbol": "SOLUSD",
            "asset_class": "spot_crypto",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.02,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15000,
    )
    assert projection.product is not None
    assert _dynamic_kraken_symbol_map(
        ({"product": projection.product},)
    ) == {"kraken:solusd": "SOL/USD"}


def test_quote_telemetry_accepts_dynamic_provider_symbol() -> None:
    ts = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
    quote = RawQuote(
        asset_id="kraken:solusd",
        venue="Kraken",
        source_id="kraken_public",
        bid=149.0,
        ask=151.0,
        last=150.0,
        mark=150.0,
        exchange_ts=ts,
        received_ts=ts,
        adapter_version="test",
    )
    payload = _quote_telemetry(
        quote,
        symbol_by_asset={"kraken:solusd": "SOL/USD"},
    )
    assert payload["asset_id"] == "kraken:solusd"
    assert payload["symbol"] == "SOL/USD"
