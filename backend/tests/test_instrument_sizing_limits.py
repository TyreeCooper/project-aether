from app.desk import MultiDesk
from app.instruments import instrument_spec
from app.paper_portfolio import PaperPortfolio


def test_fx_risk_sizing_clips_to_one_standard_lot():
    portfolio = PaperPortfolio(1_000_000.0)

    eur_qty = portfolio.size_for_risk(
        "eurusd",
        side="long",
        risk_usd=100_000.0,
        entry_price=1.1000,
        stop_price=1.0900,
    )
    jpy_qty = portfolio.size_for_risk(
        "usdjpy",
        side="long",
        risk_usd=100_000.0,
        entry_price=150.0,
        stop_price=149.0,
    )

    assert eur_qty == 100_000.0
    assert jpy_qty == 100_000.0


def test_fx_open_position_stores_units_and_standard_lots_and_clips_direct_request():
    portfolio = PaperPortfolio(1_000_000.0)

    opened = portfolio.open_position(
        "eurusd",
        side="long",
        quantity=250_000.0,
        price=1.10,
        stop_price=1.09,
    )

    assert opened["ok"] is True
    assert opened["quantity"] == 100_000.0
    assert opened["qty"] == 100_000.0
    assert opened["quantity_unit"] == "EUR units"
    assert opened["base_units"] == 100_000.0
    assert opened["standard_lot_units"] == 100_000.0
    assert opened["standard_lots"] == 1.0
    assert opened["max_standard_lots"] == 1.0
    assert opened["max_quantity"] == 100_000.0
    assert opened["hard_quantity_cap_applied"] is True


def test_each_micro_future_risk_size_and_direct_open_are_capped_to_one_contract():
    cases = {
        "mes": (6000.0, 5990.0),
        "mnq": (21000.0, 20990.0),
        "mgc": (3000.0, 2990.0),
        "mcl": (70.0, 69.0),
        "us10y": (110.0, 109.0),
    }

    for aid, (entry, stop) in cases.items():
        portfolio = PaperPortfolio(10_000_000.0)
        sized = portfolio.size_for_risk(
            aid,
            side="long",
            risk_usd=1_000_000.0,
            entry_price=entry,
            stop_price=stop,
        )
        assert sized == 1.0, aid

        opened = portfolio.open_position(
            aid,
            side="long",
            quantity=5.0,
            price=entry,
            stop_price=stop,
        )
        assert opened["ok"] is True, (aid, opened)
        assert opened["quantity"] == 1.0
        assert opened["contracts"] == 1.0
        assert opened["quantity_unit"] == "contracts"
        assert opened["max_quantity"] == 1.0
        assert opened["hard_quantity_cap_applied"] is True


def test_equities_and_crypto_are_not_blanket_capped_to_one_unit():
    portfolio = PaperPortfolio(10_000_000.0)

    nvda = portfolio.size_for_risk(
        "nvda",
        side="long",
        risk_usd=10_000.0,
        entry_price=200.0,
        stop_price=199.0,
    )
    eth = portfolio.size_for_risk(
        "eth",
        side="long",
        risk_usd=10_000.0,
        entry_price=4000.0,
        stop_price=3900.0,
    )

    assert nvda > 1.0
    assert eth > 1.0
    assert instrument_spec("nvda").get("max_quantity") is None
    assert instrument_spec("eth").get("max_quantity") is None

    stock = portfolio.open_position(
        "nvda",
        side="long",
        quantity=25.0,
        price=200.0,
        stop_price=190.0,
        position_key="nvda:test",
    )
    crypto = portfolio.open_position(
        "eth",
        side="long",
        quantity=2.0,
        price=4000.0,
        stop_price=3800.0,
        position_key="eth:test",
    )
    assert stock["ok"] is True
    assert stock["quantity"] == 25.0
    assert stock["shares"] == 25.0
    assert stock["hard_quantity_cap_applied"] is False

    assert crypto["ok"] is True
    assert crypto["quantity"] == 2.0
    assert crypto["coin_quantity"] == 2.0
    assert crypto["hard_quantity_cap_applied"] is False


def test_below_minimum_risk_size_still_produces_zero_quantity():
    portfolio = PaperPortfolio(300_000.0)
    qty = portfolio.size_for_risk(
        "mes",
        side="long",
        risk_usd=1.0,
        entry_price=6000.0,
        stop_price=5990.0,
    )
    assert qty == 0.0


def test_entry_plan_reports_unambiguous_fx_and_future_units():
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(1_000_000.0)
    for base in desk.books:
        base.wallet = desk.wallet
    for route_book in desk.route_books.values():
        route_book.wallet = desk.wallet

    eur = desk.route_books["eurusd:scalp"]
    eur.mark = 1.10
    eur.bid = 1.0999
    eur.ask = 1.1001
    eur_plan = eur.entry_plan(
        100_000.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "scalp",
            "risk_stop_pct": 0.25,
            "position_key": "eurusd:scalp",
        },
        max_capital_usd=1_000_000.0,
    )
    assert eur_plan["ok"] is True
    assert eur_plan["qty"] <= 100_000.0
    assert eur_plan["quantity_unit"] == "EUR units"
    assert eur_plan["standard_lots"] <= 1.0
    assert eur_plan["max_standard_lots"] == 1.0

    mes = desk.route_books["mes:scalp"]
    mes.mark = 6000.0
    mes.bid = 5999.75
    mes.ask = 6000.25
    mes_plan = mes.entry_plan(
        100_000.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "scalp",
            "risk_stop_pct": 1.0,
            "position_key": "mes:scalp",
        },
        max_capital_usd=1_000_000.0,
    )
    assert mes_plan["ok"] is True
    assert mes_plan["qty"] == 1.0
    assert mes_plan["contracts"] == 1.0
    assert mes_plan["quantity_unit"] == "contracts"


def test_sizing_policy_is_machine_visible():
    desk = MultiDesk(execution_test_mode=False)
    policy = desk.settings_snapshot()["instrument_sizing_policy"]

    assert policy["fx_max_standard_lots"] == 1.0
    assert policy["fx_max_base_units"] == 100_000.0
    assert policy["micro_future_max_contracts"] == 1.0
    assert policy["equity_quantity_unit"] == "shares"
    assert policy["crypto_quantity_unit"] == "coin_quantity"
