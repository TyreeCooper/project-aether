from app.desk import MultiDesk
from app.paper_portfolio import PaperPortfolio


def _fresh_desk(usd=20_000):
    desk = MultiDesk()
    desk.wallet = PaperPortfolio(usd)
    for book in desk.books:
        book.wallet = desk.wallet
        book.fills = []
        book.stop = 0.0
        book.highest = 0.0
        book.lowest = 0.0
        book.entry_at = None
        book.entry_mode = None
        book.last_entry_signal_key = None
    desk.activity_events = []
    return desk


def test_duration_helper_is_exact_for_closed_trade():
    seconds = MultiDesk._duration_seconds(
        "2026-09-22T12:00:00+00:00",
        "2026-09-22T12:43:46+00:00",
    )
    assert seconds == 2626


def test_live_trades_reports_open_position_and_trade_identity():
    desk = _fresh_desk()
    book = desk.by_id["nvda"]
    book.mark = 101.0
    book.bid = 100.9
    book.ask = 101.1

    opened = desk.wallet.open_position(
        "nvda",
        side="long",
        quantity=10,
        price=100.0,
        stop_price=98.0,
        opened_at="2026-09-22T12:00:00+00:00",
        mode="intraday",
        signal_key="nvda:1",
        metadata={
            "entry_reason": "qualified_intraday_grain",
            "quality_score": 90,
            "entry_clock": "15m",
            "bias_clock": "1d/4h",
        },
    )
    assert opened["ok"] is True
    book.entry_at = opened["opened_at"]
    book.entry_mode = "intraday"
    book.stop = 98.0
    book.highest = 101.0
    book.lowest = 99.5

    snap = desk.live_trades()
    assert snap["state"] == "trading"
    assert snap["open_count"] == 1
    trade = snap["items"][0]
    assert trade["trade_id"] == opened["trade_id"]
    assert trade["asset_id"] == "nvda"
    assert trade["side"] == "long"
    assert trade["quantity"] == 10
    assert trade["entry_price"] == 100.0
    assert trade["current_price"] == 101.0
    assert trade["entry_reason"] == "qualified_intraday_grain"
    assert trade["duration_seconds"] >= 0


def test_blotter_is_round_trip_not_two_fill_rows():
    desk = _fresh_desk()
    opened = desk.wallet.open_position(
        "eurusd",
        side="short",
        quantity=10_000,
        price=1.1000,
        opened_at="2026-09-22T12:00:00+00:00",
        mode="intraday",
        signal_key="fx:1",
    )
    assert opened["ok"] is True
    closed = desk.wallet.close_position(
        "eurusd",
        price=1.0990,
        closed_at="2026-09-22T12:30:00+00:00",
        exit_reason="rule_exit",
    )
    assert closed["ok"] is True

    rows = desk.blotter()
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_id"] == opened["trade_id"]
    assert row["side"] == "short"
    assert row["duration_seconds"] == 1800
    assert row["entry_price"] == 1.1000
    assert row["exit_price"] == 1.0990
    assert row["realized_pnl_usd"] > 0


def test_raw_fill_ledger_remains_separate_from_blotter():
    desk = _fresh_desk()
    book = desk.by_id["pltr"]
    book.fills = [
        {
            "trade_id": "t-1",
            "event": "entry",
            "side": "buy",
            "qty": 10,
            "price": 100,
            "ts": "2026-09-22T12:00:00+00:00",
        },
        {
            "trade_id": "t-1",
            "event": "exit",
            "side": "sell",
            "qty": 10,
            "price": 101,
            "ts": "2026-09-22T12:30:00+00:00",
        },
    ]
    fills = desk.fill_ledger()
    assert len(fills) == 2
    assert {row["event"] for row in fills} == {"entry", "exit"}


def test_activity_event_has_trade_and_asset_context():
    desk = _fresh_desk()
    book = desk.by_id["mes"]
    row = desk._record_event(
        "entry_filled",
        book,
        {
            "trade_id": "trade-123",
            "side": "long",
            "price": 5000.0,
        },
    )
    assert row["trade_id"] == "trade-123"
    assert row["asset_id"] == "mes"
    assert row["event_type"] == "entry_filled"
    assert desk.trade_events(1)[0]["event_id"] == row["event_id"]

def test_restore_backfills_legacy_open_timestamp_for_live_timer():
    desk = _fresh_desk()
    book = desk.by_id["btc"]
    book.mark = 87_000.0

    opened_at = "2020-01-01T12:00:00+00:00"
    opened = desk.wallet.open_position(
        "btc",
        side="long",
        quantity=0.001,
        price=86_000.0,
        opened_at=opened_at,
        mode="daily_swing",
    )
    assert opened["ok"] is True

    wallet = desk.wallet.payload()
    wallet["positions"]["btc"]["opened_at"] = None
    desk._restore(
        {
            "wallet": wallet,
            "books": {
                "btc": {
                    "entry_at": opened_at,
                    "entry_mode": "daily_swing",
                    "fills": [],
                }
            },
        }
    )

    restored = desk.wallet.position("btc")
    assert restored is not None
    assert restored["opened_at"] == opened_at

    live = desk.live_trades()
    trade = next(row for row in live["items"] if row["asset_id"] == "btc")
    assert trade["opened_at"] == opened_at
    assert trade["duration_seconds"] is not None
    assert trade["duration_seconds"] > 0

