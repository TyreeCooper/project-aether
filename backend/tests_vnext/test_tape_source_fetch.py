from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aether_vnext.tape_sources import (
    COINBASE_TAPE_SOURCE_ID,
    parse_coinbase_exchange_book,
    fetch_databento_glbx_mbp1,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 18, 5, tzinfo=UTC)


def test_coinbase_level1_book_normalizes_to_tape_bbo() -> None:
    row = parse_coinbase_exchange_book(
        {
            "sequence": 123,
            "bids": [["99999.25", "1.0", 2]],
            "asks": [["100000.75", "1.2", 3]],
        },
        asset_id="btc",
        product_id="BTC-USD",
        received_at_utc=NOW,
    )
    assert row is not None
    assert row.source_id == COINBASE_TAPE_SOURCE_ID
    assert row.bid == 99999.25
    assert row.ask == 100000.75
    assert row.mark == 100000.0


@pytest.mark.asyncio
async def test_databento_fetch_fails_closed_without_credential(monkeypatch) -> None:
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="databento_api_key_missing"):
        await fetch_databento_glbx_mbp1(
            asset_id="mes",
            source_symbol="MESZ6",
        )
