from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from aether_vnext.kraken_ingress_supervisor import (
    KrakenIngressSupervisor,
    _quote_telemetry,
    configured_ingress_enabled,
    configured_ingress_interval_seconds,
    validate_configured_ingress_environment,
)
from aether_vnext.market_data import RawQuote


def test_ingress_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_VNEXT_KRAKEN_INGRESS_ENABLED", raising=False)
    assert configured_ingress_enabled() is False
    validate_configured_ingress_environment()


def test_enabled_ingress_refuses_non_burnin(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_VNEXT_KRAKEN_INGRESS_ENABLED", "true")
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="only run in burnin"):
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
