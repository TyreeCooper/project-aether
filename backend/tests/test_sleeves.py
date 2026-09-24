from app.sleeves import ASSET_SLEEVE, SleeveBook, sleeve_for_asset


def test_seed_weights_sum_to_starting_cash():
    book = SleeveBook.seed(10_000)
    assert round(book.cash_available_usd, 6) == 10_000.0
    assert book.sleeve("kraken_paper").cash_available_usd == 4_000.0
    assert book.sleeve("tastyfx_paper").cash_available_usd == 2_000.0
    assert book.sleeve("ninja_paper").cash_available_usd == 2_000.0
    assert book.sleeve("ibkr_paper").cash_available_usd == 2_000.0


def test_300k_default_bank_splits_40_20_20_20():
    book = SleeveBook.seed(300_000)
    assert book.sleeve("kraken_paper").cash_available_usd == 120_000.0
    assert book.sleeve("ibkr_paper").cash_available_usd == 60_000.0


def test_twelve_assets_map_to_four_sleeves():
    assert len(ASSET_SLEEVE) == 12
    assert sleeve_for_asset("btc") == "kraken_paper"
    assert sleeve_for_asset("eurusd") == "tastyfx_paper"
    assert sleeve_for_asset("mes") == "ninja_paper"
    assert sleeve_for_asset("nvda") == "ibkr_paper"


def test_reserve_is_sleeve_local_not_consolidated():
    book = SleeveBook.seed(10_000)
    held = book.reserve("nvda", 2_000, intent_id="t1")
    assert held["ok"] is True
    assert book.sleeve("ibkr_paper").cash_available_usd == 0.0
    assert book.sleeve("ibkr_paper").cash_reserved_usd == 2_000.0
    denied = book.reserve("pltr", 1.0, intent_id="t2")
    assert denied["ok"] is False
    assert denied["error"] == "insufficient_capital"
    assert book.sleeve("kraken_paper").cash_available_usd == 4_000.0


def test_no_cross_sleeve_borrow():
    book = SleeveBook.seed(10_000)
    book.reserve("btc", 4_000, intent_id="btc")
    denied = book.reserve("btc", 1.0, intent_id="btc2")
    assert denied["error"] == "insufficient_capital"


def test_transfer_moves_available_only():
    book = SleeveBook.seed(10_000)
    book.reserve("btc", 1_000, intent_id="x")
    blocked = book.transfer("kraken_paper", "ibkr_paper", 3_500, reason="rebalance", actor="gov")
    assert blocked["ok"] is False
    ok = book.transfer("kraken_paper", "ibkr_paper", 2_000, reason="rebalance", actor="gov")
    assert ok["ok"] is True
    assert book.sleeve("kraken_paper").cash_available_usd == 1_000.0
    assert book.sleeve("ibkr_paper").cash_available_usd == 4_000.0


def test_restore_round_trip_does_not_reseed():
    book = SleeveBook.seed(10_000)
    book.reserve("mes", 500, intent_id="m")
    restored = SleeveBook.restore(book.payload(), 10_000)
    assert restored.sleeve("ninja_paper").cash_reserved_usd == 500.0
    assert restored.cash_available_usd == 9_500.0
