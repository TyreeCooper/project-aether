from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.prototype_market_history import (
    PrototypeMarketBar,
    load_prototype_market_bars,
    load_prototype_market_bars_for_assets,
    persist_prototype_market_bars,
    prototype_market_bar_id,
    summarize_prototype_market_history,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)


def _bar(hour: int, close: float) -> PrototypeMarketBar:
    opened = T0 + timedelta(hours=hour)
    return PrototypeMarketBar(
        asset_id="btc",
        interval_seconds=3600,
        bucket_open_utc=opened,
        bucket_close_utc=opened + timedelta(hours=1),
        open=close - 10,
        high=close + 20,
        low=close - 20,
        close=close,
        volume=12.5,
        trade_count=50,
        source_id="kraken_public_trades",
        source_ref="test-source",
        available_at_utc=opened + timedelta(hours=1),
    )


def test_prototype_market_bar_ledger_is_separate_and_idempotent() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = VNextStore(schema=None)
    store.create_all_for_test(engine)

    b0 = _bar(0, 100_000.0)
    b1 = _bar(1, 100_500.0)
    assert prototype_market_bar_id(b0) != prototype_market_bar_id(b1)

    with engine.begin() as conn:
        assert persist_prototype_market_bars(
            conn, store, (b0, b1), ingested_at_utc=T0 + timedelta(hours=2)
        ) == 2
        assert persist_prototype_market_bars(
            conn, store, (b0, b1), ingested_at_utc=T0 + timedelta(hours=3)
        ) == 0

        rows = load_prototype_market_bars(
            conn,
            store,
            asset_id="btc",
            interval_seconds=3600,
            end_at_utc=T0 + timedelta(hours=3),
        )
        assert [row.close for row in rows] == [100_000.0, 100_500.0]
        assert "research_bars" in store.tables
        assert "prototype_market_bars" in store.tables


def test_prototype_history_never_returns_future_unavailable_bar() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = VNextStore(schema=None)
    store.create_all_for_test(engine)
    bar = _bar(0, 100_000.0)

    with engine.begin() as conn:
        persist_prototype_market_bars(
            conn, store, (bar,), ingested_at_utc=T0 + timedelta(hours=1)
        )
        assert load_prototype_market_bars(
            conn,
            store,
            asset_id="btc",
            interval_seconds=3600,
            end_at_utc=T0 + timedelta(minutes=59),
        ) == ()
        assert len(load_prototype_market_bars(
            conn,
            store,
            asset_id="btc",
            interval_seconds=3600,
            end_at_utc=T0 + timedelta(hours=1),
        )) == 1



def test_bulk_history_load_returns_all_requested_assets_with_one_select() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = VNextStore(schema=None)
    store.create_all_for_test(engine)

    btc = _bar(0, 100_000.0)
    eth = PrototypeMarketBar(
        asset_id="eth",
        interval_seconds=3600,
        bucket_open_utc=T0,
        bucket_close_utc=T0 + timedelta(hours=1),
        open=2_000.0,
        high=2_020.0,
        low=1_980.0,
        close=2_010.0,
        volume=20.0,
        trade_count=25,
        source_id="kraken_public_trades",
        source_ref="test-source",
        available_at_utc=T0 + timedelta(hours=1),
    )
    with engine.begin() as conn:
        assert persist_prototype_market_bars(
            conn,
            store,
            (btc, eth),
            ingested_at_utc=T0 + timedelta(hours=1),
        ) == 2

    statements = []
    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", record_statement)
    try:
        with engine.begin() as conn:
            grouped = load_prototype_market_bars_for_assets(
                conn,
                store,
                asset_ids=("btc", "eth", "kraken:solusd"),
                interval_seconds=3600,
                end_at_utc=T0 + timedelta(hours=2),
            )
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_statement)

    assert [row.asset_id for row in grouped["btc"]] == ["btc"]
    assert [row.asset_id for row in grouped["eth"]] == ["eth"]
    assert grouped["kraken:solusd"] == ()
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1


def test_idempotent_bar_persistence_uses_bounded_bulk_lookup() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = VNextStore(schema=None)
    store.create_all_for_test(engine)
    bars = tuple(_bar(hour, 100_000.0 + hour) for hour in range(20))
    with engine.begin() as conn:
        assert persist_prototype_market_bars(
            conn,
            store,
            bars,
            ingested_at_utc=T0 + timedelta(days=2),
        ) == len(bars)

    statements = []
    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", record_statement)
    try:
        with engine.begin() as conn:
            inserted = persist_prototype_market_bars(
                conn,
                store,
                bars,
                ingested_at_utc=T0 + timedelta(days=3),
            )
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_statement)

    assert inserted == 0
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    inserts = [s for s in statements if s.lstrip().upper().startswith("INSERT")]
    assert len(selects) == 1
    assert inserts == []



def test_history_summary_uses_one_grouped_query_without_loading_bar_rows() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = VNextStore(schema=None)
    store.create_all_for_test(engine)

    bars = tuple(_bar(hour, 100_000.0 + hour) for hour in range(20))
    with engine.begin() as conn:
        assert persist_prototype_market_bars(
            conn,
            store,
            bars,
            ingested_at_utc=T0 + timedelta(days=2),
        ) == len(bars)

    statements = []
    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", record_statement)
    try:
        with engine.begin() as conn:
            summary = summarize_prototype_market_history(
                conn,
                store,
                asset_ids=("btc", "eth"),
                end_at_utc=T0 + timedelta(days=2),
            )
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_statement)

    key = ("btc", 3600, "kraken_public_trades")
    assert summary[key]["bar_count"] == 20
    assert summary[key]["latest_close_utc"] == T0 + timedelta(hours=20)
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "GROUP BY" in selects[0].upper()
