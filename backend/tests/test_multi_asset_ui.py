from app.desk import MultiDesk


def test_floor_and_asset_views_are_multi_asset_and_isolated():
    desk = MultiDesk()
    floor = desk.floor_snapshot()
    assert floor["strategy_name"] == "Aether Vector Engine"
    assert len(floor["assets"]) == 12
    assert {row["id"] for row in floor["assets"]} == {
        "eurusd",
        "usdjpy",
        "mes",
        "mnq",
        "mgc",
        "mcl",
        "us10y",
        "nvda",
        "tsla",
        "pltr",
        "btc",
        "eth",
    }

    btc = desk.asset_snapshot("btc")
    eth = desk.asset_snapshot("eth")
    assert btc is not None and eth is not None
    assert btc["asset"]["id"] == "btc"
    assert eth["asset"]["id"] == "eth"
    assert btc["asset"]["pair"] == "BTC/USD"
    assert eth["asset"]["pair"] == "ETH/USD"
    assert desk.asset_snapshot("does-not-exist") is None


def test_register_dynamic_asset_book_is_isolated():
    desk = MultiDesk()
    # Exercise runtime registration without network seeding.
    from app.universe import register_asset
    from app.pair_book import PairBook

    asset = register_asset(
        {
            "id": "testcoin",
            "name": "TEST",
            "symbol": "TEST",
            "pair": "TEST/USD",
            "kraken": "TESTUSD",
            "tv": "KRAKEN:TESTUSD",
            "binance": "TESTUSD",
            "paper": True,
        }
    )
    if "testcoin" not in desk.by_id:
        book = PairBook(asset, desk.wallet)
        desk.books.append(book)
        desk.by_id[book.id] = book

    page = desk.asset_snapshot("testcoin")
    assert page is not None
    assert page["asset"]["pair"] == "TEST/USD"
    assert page["asset"]["id"] == "testcoin"
    assert desk.asset_snapshot("eth")["asset"]["pair"] == "ETH/USD"


def test_armed_status_tracks_multi_asset_allocator():
    desk = MultiDesk()
    desk.armed = False
    state = desk.engine_status()
    assert state["armed"] is False
    assert state["accepting_entries"] is False

    desk.armed = True
    state = desk.engine_status()
    assert state["armed"] is True
    # A desk is only reported as accepting entries when its loop is actually alive.
    assert state["accepting_entries"] is bool(state["running"])


def test_desk_settings_are_bounded_and_reported():
    desk = MultiDesk()
    out = desk.update_settings(
        allocation_per_entry_pct=12.5,
        quote_poll_seconds=30,
    )
    assert out["allocation_per_entry_pct"] == 12.5
    assert out["quote_poll_seconds"] == 30
    assert desk.risk_slice == 0.125
    assert desk.poll_seconds == 30


def test_floor_exposes_intelligence_without_inventing_news():
    desk = MultiDesk()
    floor = desk.floor_snapshot()
    intel = floor["intelligence"]
    assert len(intel["assets"]) >= 10
    assert "opportunity_ranking" in intel
    assert intel["risk"]["calendar_connected"] is False
    assert any(x["id"] == "kraken" and x["status"] == "connected" for x in intel["sources"])
    page = desk.asset_snapshot("eth")
    assert page is not None
    assert page["intelligence"]["attribution"]["status"] == "unavailable"
    assert page["intelligence"]["community"]["status"] == "unavailable"
