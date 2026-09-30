from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.prototype_market_history import (
    PrototypeMarketBar,
    load_prototype_market_bars,
    persist_prototype_market_bars,
    prototype_market_bar_id,
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
