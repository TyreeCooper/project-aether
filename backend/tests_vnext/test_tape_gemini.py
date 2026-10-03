from __future__ import annotations

from datetime import datetime, timezone

from aether_vnext.tape_sources import (
    GEMINI_TAPE_SOURCE_ID,
    parse_gemini_public_ticker,
    tape_source_status,
)


NOW = datetime(2026, 10, 3, 18, 30, tzinfo=timezone.utc)


def test_gemini_is_fourth_independent_public_crypto_tape_source() -> None:
    row = parse_gemini_public_ticker(
        {"bid": "99999.50", "ask": "100000.50", "last": "100000.00"},
        asset_id="btc",
        source_symbol="BTCUSD",
        received_at_utc=NOW,
    )
    assert row is not None
    assert row.source_id == GEMINI_TAPE_SOURCE_ID
    assert row.bid == 99999.5
    assert row.ask == 100000.5
    assert row.mark == 100000.0

    status = {item["source_id"]: item for item in tape_source_status()}
    assert status[GEMINI_TAPE_SOURCE_ID]["state"] == "READY"
    assert status[GEMINI_TAPE_SOURCE_ID]["independent"] is True
