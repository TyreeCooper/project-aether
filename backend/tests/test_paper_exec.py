from app.paper_exec import deny_microstructure, slipped_price


def test_buy_slips_above_ask():
    assert slipped_price("buy", 100.0, 100.2, 100.1) > 100.2


def test_sell_slips_below_bid():
    assert slipped_price("sell", 100.0, 100.2, 100.1) < 100.0


def test_deny_stale_and_fallback():
    assert (
        deny_microstructure(
            side="buy",
            bid=1,
            ask=1.01,
            mark=1,
            source="kraken",
            stale=True,
            watch_last=1,
        )
        == "stale_mark"
    )
    assert (
        deny_microstructure(
            side="buy",
            bid=1,
            ask=1.01,
            mark=1,
            source="coingecko",
            stale=False,
            watch_last=1,
        )
        == "fallback_mark"
    )


def test_wide_basis_blocks_entries():
    assert (
        deny_microstructure(
            side="buy",
            bid=100,
            ask=100.01,
            mark=100,
            source="kraken",
            stale=False,
            watch_last=181,
        )
        == "wide_basis"
    )


def test_protective_exits_not_blocked():
    assert (
        deny_microstructure(
            side="sell",
            bid=1,
            ask=1.2,
            mark=1,
            source="kraken",
            stale=True,
            watch_last=200,
            protective=True,
        )
        is None
    )
