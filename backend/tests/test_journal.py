import pytest

from app.journal import JOURNAL_SCHEMA_VERSION, TradeJournalEntry, dump_journal, load_journal


def _entry() -> TradeJournalEntry:
    return TradeJournalEntry(
        event_id="fill-1",
        ts="2026-09-22T18:50:00+00:00",
        event="fill",
        strategy_id="trend_breakout",
        strategy_version="v3",
        horizon="intraday",
        payload={"side": "buy", "qty": 0.01, "paper": True},
    )


def test_journal_round_trip_preserves_strategy_attribution():
    original = _entry()
    replayed = load_journal(dump_journal([original]))
    assert replayed == [original]
    assert replayed[0].strategy_id == "trend_breakout"
    assert replayed[0].strategy_version == "v3"
    assert replayed[0].horizon == "intraday"
    assert replayed[0].payload["paper"] is True


def test_journal_serialization_is_deterministic():
    entry = _entry()
    assert dump_journal([entry]) == dump_journal([entry])


def test_journal_rejects_unknown_schema_version():
    raw = '{"schema_version":999,"event_id":"x"}\n'
    with pytest.raises(ValueError, match="unsupported_journal_schema"):
        load_journal(raw)


def test_journal_requires_attribution_fields():
    with pytest.raises(ValueError, match="journal_strategy_version_required"):
        TradeJournalEntry(
            event_id="fill-1",
            ts="2026-09-22T18:50:00+00:00",
            event="fill",
            strategy_id="trend_breakout",
            strategy_version="",
            horizon="intraday",
            payload={},
            schema_version=JOURNAL_SCHEMA_VERSION,
        )
