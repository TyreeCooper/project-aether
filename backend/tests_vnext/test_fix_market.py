from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.fix_market import (
    FIX_BID,
    FIX_MARKET_DATA_REJECT,
    FIX_MARKET_DATA_REQUEST,
    FIX_MARKET_DATA_SNAPSHOT,
    FIX_OFFER,
    FIX_TRADE,
    FixField,
    parse_fix_message,
    parse_market_data_reject,
    parse_market_data_snapshot,
    render_application_fields,
    snapshot_to_raw_quote,
    top_of_book_snapshot_request_fields,
)


UTC = timezone.utc


def test_standard_top_of_book_snapshot_request_fields_are_application_only() -> None:
    fields = top_of_book_snapshot_request_fields(
        md_req_id="aether-eurusd-1",
        symbol="EUR/USD",
    )

    assert fields == (
        FixField(35, FIX_MARKET_DATA_REQUEST),
        FixField(262, "aether-eurusd-1"),
        FixField(263, "0"),
        FixField(264, "1"),
        FixField(267, "2"),
        FixField(269, FIX_BID),
        FixField(269, FIX_OFFER),
        FixField(146, "1"),
        FixField(55, "EUR/USD"),
    )
    rendered = render_application_fields(fields, delimiter="|")
    assert rendered == (
        "35=V|262=aether-eurusd-1|263=0|264=1|267=2|"
        "269=0|269=1|146=1|55=EUR/USD|"
    )
    # Session/header/trailer values are deliberately not fabricated here.
    assert "49=" not in rendered
    assert "56=" not in rendered
    assert "34=" not in rendered
    assert "10=" not in rendered


def test_fix_parser_preserves_duplicate_group_tags() -> None:
    message = parse_fix_message(
        "8=FIXT.1.1|35=W|55=EUR/USD|268=2|"
        "269=0|270=1.1000|269=1|270=1.1002|10=000|"
    )
    assert message.msg_type == FIX_MARKET_DATA_SNAPSHOT
    assert message.values(269) == (FIX_BID, FIX_OFFER)


def test_snapshot_decoder_produces_uncrossed_reviewed_bbo() -> None:
    snapshot = parse_market_data_snapshot(
        "8=FIXT.1.1|35=W|52=20260927-05:45:01.125|"
        "262=aether-eurusd-1|55=EUR/USD|268=3|"
        "269=0|270=1.1000|290=1|"
        "269=1|270=1.1002|290=1|"
        "269=2|270=1.1001|10=000|"
    )

    assert snapshot.md_req_id == "aether-eurusd-1"
    assert snapshot.symbol == "EUR/USD"
    assert snapshot.bid == 1.1000
    assert snapshot.ask == 1.1002
    assert snapshot.last == 1.1001
    assert snapshot.source_timestamp_utc == datetime(
        2026, 9, 27, 5, 45, 1, 125000, tzinfo=UTC
    )

    raw = snapshot_to_raw_quote(
        snapshot,
        symbol_to_asset={"EUR/USD": "eurusd"},
        venue="tastyfx",
        source_id="test.fix.source",
        received_at_utc=datetime(
            2026, 9, 27, 5, 45, 1, 200000, tzinfo=UTC
        ),
    )
    assert raw.asset_id == "eurusd"
    assert raw.bid == 1.1000
    assert raw.ask == 1.1002
    assert raw.last == 1.1001
    assert raw.mark == pytest.approx(1.1001)


def test_snapshot_decoder_rejects_crossed_or_ambiguous_book() -> None:
    with pytest.raises(ValueError, match="crossed"):
        parse_market_data_snapshot(
            "8=FIXT.1.1|35=W|55=EUR/USD|268=2|"
            "269=0|270=1.1003|269=1|270=1.1002|10=000|"
        )

    with pytest.raises(ValueError, match="ambiguous"):
        parse_market_data_snapshot(
            "8=FIXT.1.1|35=W|55=EUR/USD|268=3|"
            "269=0|270=1.1000|"
            "269=0|270=1.0999|"
            "269=1|270=1.1002|10=000|"
        )


def test_snapshot_decoder_requires_exact_group_count_and_prices() -> None:
    with pytest.raises(ValueError, match="does not match"):
        parse_market_data_snapshot(
            "8=FIXT.1.1|35=W|55=EUR/USD|268=3|"
            "269=0|270=1.1000|269=1|270=1.1002|10=000|"
        )

    with pytest.raises(ValueError, match="MDEntryPx"):
        parse_market_data_snapshot(
            "8=FIXT.1.1|35=W|55=EUR/USD|268=2|"
            "269=0|270=1.1000|269=1|10=000|"
        )


def test_market_data_reject_is_structured_without_becoming_quote_evidence() -> None:
    reject = parse_market_data_reject(
        "8=FIXT.1.1|35=Y|262=aether-eurusd-1|281=0|"
        "58=Unknown symbol|10=000|"
    )
    assert reject.md_req_id == "aether-eurusd-1"
    assert reject.reject_reason == "0"
    assert reject.text == "Unknown symbol"

    with pytest.raises(ValueError, match="35=Y"):
        parse_market_data_reject(
            "8=FIXT.1.1|35=W|55=EUR/USD|268=2|"
            "269=0|270=1.1|269=1|270=1.2|10=000|"
        )


def test_unreviewed_symbol_cannot_become_raw_quote() -> None:
    snapshot = parse_market_data_snapshot(
        "8=FIXT.1.1|35=W|55=EUR/USD|268=2|"
        "269=0|270=1.1000|269=1|270=1.1002|10=000|"
    )
    with pytest.raises(ValueError, match="reviewed asset binding"):
        snapshot_to_raw_quote(
            snapshot,
            symbol_to_asset={"USD/JPY": "usdjpy"},
            venue="tastyfx",
            source_id="test.fix.source",
            received_at_utc=datetime(2026, 9, 27, 5, 45, tzinfo=UTC),
        )


def test_wrong_begin_string_and_wrong_message_type_fail_closed() -> None:
    with pytest.raises(ValueError, match="BeginString"):
        parse_fix_message("8=FIX.4.4|35=W|55=EUR/USD|")

    with pytest.raises(ValueError, match="35=W"):
        parse_market_data_snapshot(
            "8=FIXT.1.1|35=Y|262=req|281=0|10=000|"
        )
