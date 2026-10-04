from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.coinbase_prototype_history import COINBASE_SOURCE_ID
from aether_vnext.prototype_history_sources import CRYPTOCOMPARE_SOURCE_ID
from aether_vnext.prototype_history_source_pool import (
    HistoricalReferenceUnavailable,
    REFERENCE_MINIMUM_BARS,
    fetch_historical_reference_pool,
)


NOW = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_reference_pool_uses_primary_when_ready(monkeypatch) -> None:
    primary = (object(),) * REFERENCE_MINIMUM_BARS

    async def primary_fetch(**kwargs):
        return primary

    async def catalog_fetch(**kwargs):
        raise AssertionError("standby should not be touched")

    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_cryptocompare_kraken_hourly",
        primary_fetch,
    )
    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_coinbase_public_products",
        catalog_fetch,
    )

    result = await fetch_historical_reference_pool(
        asset_id="kraken:solusd",
        asset_symbol="SOL",
        end_at_utc=NOW,
    )
    assert result.selected_source_id == CRYPTOCOMPARE_SOURCE_ID
    assert result.selected_tier == 1
    assert result.bars == primary
    assert tuple(row.status for row in result.attempts) == ("READY",)


@pytest.mark.asyncio
async def test_reference_pool_promotes_coinbase_after_primary_failure(monkeypatch) -> None:
    backup = (object(),) * REFERENCE_MINIMUM_BARS

    async def primary_fetch(**kwargs):
        raise TimeoutError("primary unavailable")

    async def catalog_fetch(**kwargs):
        return {("SOL", "USD"): "SOL-USD"}

    async def backup_fetch(**kwargs):
        assert kwargs["coinbase_product"] == "SOL-USD"
        return backup

    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_cryptocompare_kraken_hourly",
        primary_fetch,
    )
    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_coinbase_public_products",
        catalog_fetch,
    )
    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_coinbase_hourly_history",
        backup_fetch,
    )

    result = await fetch_historical_reference_pool(
        asset_id="kraken:solusd",
        asset_symbol="SOL",
        end_at_utc=NOW,
    )
    assert result.selected_source_id == COINBASE_SOURCE_ID
    assert result.selected_tier == 2
    assert result.bars == backup
    assert tuple(row.status for row in result.attempts) == ("FAILED", "READY")


@pytest.mark.asyncio
async def test_reference_pool_exhaustion_reports_every_attempt(monkeypatch) -> None:
    async def primary_fetch(**kwargs):
        raise TimeoutError("primary unavailable")

    async def catalog_fetch(**kwargs):
        return {}

    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_cryptocompare_kraken_hourly",
        primary_fetch,
    )
    monkeypatch.setattr(
        "aether_vnext.prototype_history_source_pool.fetch_coinbase_public_products",
        catalog_fetch,
    )

    with pytest.raises(HistoricalReferenceUnavailable) as exc:
        await fetch_historical_reference_pool(
            asset_id="kraken:xdpusd",
            asset_symbol="XDP",
            end_at_utc=NOW,
        )
    assert tuple(row.source_id for row in exc.value.attempts) == (
        CRYPTOCOMPARE_SOURCE_ID,
        COINBASE_SOURCE_ID,
    )
    assert tuple(row.status for row in exc.value.attempts) == (
        "FAILED",
        "UNAVAILABLE",
    )


def test_reference_minimum_is_derived_from_rv14_contract() -> None:
    assert REFERENCE_MINIMUM_BARS == 2176
