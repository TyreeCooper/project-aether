import math

from app.desk import (
    ASSET_RISK_FRACTION,
    CLUSTER_RISK_FRACTION,
    PORTFOLIO_RISK_FRACTION,
    TRADE_RISK_FRACTION,
    MultiDesk,
)
from app.horizons import TradingHorizon
from app.paper_portfolio import PaperPortfolio
from app.routing import ROUTES


def _strategy_desk(monkeypatch, due_routes):
    from app import desk as desk_module

    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.armed = True
    desk.persist = lambda: None
    monkeypatch.setattr(desk, "_btc_gate", lambda: (True, False))
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: tuple(due_routes),
    )
    for base in desk.books:
        base.wallet = desk.wallet
        base.mark = {
            "eurusd": 1.10,
            "usdjpy": 150.0,
            "mes": 6000.0,
            "mnq": 21000.0,
            "mgc": 3000.0,
            "mcl": 70.0,
            "us10y": 110.0,
            "nvda": 180.0,
            "tsla": 450.0,
            "pltr": 180.0,
            "btc": 100000.0,
            "eth": 4000.0,
        }[base.id]
        spread = max(base.mark * 0.0001, 0.0001)
        base.bid = base.mark - spread
        base.ask = base.mark + spread
        base.bars.clear()
        base.bars.append(
            {
                "ts": 1_700_000_000,
                "open": base.mark,
                "high": base.mark,
                "low": base.mark,
                "close": base.mark,
                "volume": 1.0,
            }
        )
        desk._sync_asset_route_books(base.id)
    for route_book in desk.route_books.values():
        route_book.wallet = desk.wallet
    return desk


def _qualify_routes(
    desk,
    *,
    eligible,
    stop_pct=1.0,
):
    eligible = set(eligible)
    for route_book in desk.route_books.values():
        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=route_book,
        ):
            key = (
                _book.id,
                _book.routing_horizon,
            )
            if key in eligible:
                return {
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": requested_mode,
                    "reason": "b4_qualified",
                    "execution_status": "paper_long_ready",
                    "quality_score": (
                        100
                        - sorted(eligible).index(key)
                    ),
                    "risk_stop_pct": stop_pct,
                    "signal_key": (
                        f"b4:{_book.id}:"
                        f"{_book.routing_horizon}"
                    ),
                    "entry_clock": "test",
                    "bias_clock": "test",
                }
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }

        route_book.snapshot_strategy = snapshot_strategy


def test_more_than_four_low_risk_qualified_positions_can_coexist(monkeypatch):
    desk = _strategy_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SCALP],),
    )
    desk.risk_slice = 0.01
    eligible = {
        ("eurusd", "scalp"),
        ("usdjpy", "scalp"),
        ("mes", "scalp"),
        ("mnq", "scalp"),
        ("nvda", "scalp"),
        ("tsla", "scalp"),
        ("pltr", "scalp"),
    }
    _qualify_routes(desk, eligible=eligible)

    out = desk._allocate()
    successful = [
        row for row in out
        if row.get("ok")
    ]

    assert len(successful) > 4
    assert len(desk.wallet.positions) == len(successful)
    assert desk.wallet.usd >= 0.0
    assert desk.wallet.test_overflow_usd == 0.0

    risk = desk.strategy_risk_snapshot()
    assert (
        risk["open_stop_risk_usd"]
        <= risk["max_portfolio_risk_usd"] + 1e-6
    )
    assert all(
        desk.wallet.position_stop_risk_usd(
            str(pos["asset_id"]),
            position_key=key,
        )
        <= risk["max_trade_risk_usd"] + 1e-6
        for key, pos in desk.wallet.positions.items()
    )


def test_aggregate_open_risk_ceiling_rejects_fifth_full_risk_candidate(monkeypatch):
    desk = _strategy_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SWING],),
    )
    equity = 300_000.0
    trade_risk = equity * TRADE_RISK_FRACTION
    assert math.isclose(trade_risk, 2_250.0)

    # Four existing strategy positions each carry exactly 0.75% stop-risk.
    # The candidate is in another cluster so the aggregate gate is the one
    # that must reject it.
    for index, aid in enumerate(("nvda", "tsla", "pltr", "eurusd")):
        entry = float(desk.by_id[aid].mark)
        qty = 10_000.0 if aid == "eurusd" else 100.0
        distance = trade_risk / qty
        opened = desk.wallet.open_position(
            aid,
            side="long",
            quantity=qty,
            price=entry,
            stop_price=entry - distance,
            mode="swing",
            position_key=f"{aid}:seed-{index}",
            metadata={
                "cluster": (
                    "fx"
                    if aid == "eurusd"
                    else "us_equity_beta"
                ),
                "routing_horizon": "swing",
            },
            test_allow_sleeve_overflow=True,
        )
        assert opened["ok"] is True

    # Restore wallet references after direct seeding.
    for route_book in desk.route_books.values():
        route_book.wallet = desk.wallet

    candidate = {("mcl", "swing")}
    _qualify_routes(
        desk,
        eligible=candidate,
        stop_pct=1.0,
    )

    out = desk._allocate()
    assert not any(row.get("ok") for row in out)
    rows = [
        row
        for row in desk.opportunity_evaluations_snapshot(100)
        if row["asset_id"] == "mcl"
        and row["routing_horizon"] == "swing"
    ]
    assert rows
    assert rows[0]["rejection_reason"] == (
        "aggregate_open_risk_limit"
    )
    risk = desk.strategy_risk_snapshot(equity)
    assert math.isclose(
        risk["open_stop_risk_usd"],
        equity * PORTFOLIO_RISK_FRACTION,
        rel_tol=0,
        abs_tol=1e-6,
    )


def test_asset_exposure_limit_rejects_third_full_risk_horizon(monkeypatch):
    desk = _strategy_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SWING],),
    )
    equity = 300_000.0
    trade_risk = equity * TRADE_RISK_FRACTION

    entry = float(desk.by_id["nvda"].mark)
    qty = 100.0
    for horizon in ("scalp", "intraday"):
        opened = desk.wallet.open_position(
            "nvda",
            side="long",
            quantity=qty,
            price=entry,
            stop_price=(
                entry - trade_risk / qty
            ),
            mode=horizon,
            position_key=f"nvda:{horizon}",
            metadata={
                "cluster": "us_equity_beta",
                "routing_horizon": horizon,
            },
        )
        assert opened["ok"] is True

    _qualify_routes(
        desk,
        eligible={("nvda", "swing")},
    )
    out = desk._allocate()
    assert not any(row.get("ok") for row in out)

    rows = [
        row
        for row in desk.opportunity_evaluations_snapshot(100)
        if row["asset_id"] == "nvda"
        and row["routing_horizon"] == "swing"
    ]
    assert rows
    assert rows[0]["rejection_reason"] == "asset_risk_limit"
    current_equity = desk.wallet.equity(desk.marks())
    assert math.isclose(
        float(rows[0]["asset_risk_limit_usd"]),
        current_equity * ASSET_RISK_FRACTION,
        rel_tol=0,
        abs_tol=1e-6,
    )


def test_cluster_exposure_limit_rejects_otherwise_valid_setup(monkeypatch):
    desk = _strategy_desk(
        monkeypatch,
        (ROUTES[TradingHorizon.SCALP],),
    )
    equity = 300_000.0
    cluster_limit = equity * CLUSTER_RISK_FRACTION
    risk_each = cluster_limit / 3.0

    for index, aid in enumerate(("mes", "nvda", "tsla")):
        # Use equity-like manual rows for deterministic risk math while
        # preserving each real asset's cluster identity.
        if aid == "mes":
            # MES point value is $5, so 450 points at one contract
            # produces the same 0.75%-equity risk.
            qty = 1.0
            entry = float(desk.by_id[aid].mark)
            stop = entry - risk_each / 5.0
        else:
            qty = 100.0
            entry = float(desk.by_id[aid].mark)
            stop = entry - risk_each / qty
        opened = desk.wallet.open_position(
            aid,
            side="long",
            quantity=qty,
            price=entry,
            stop_price=stop,
            mode="swing",
            position_key=f"{aid}:seed-{index}",
            metadata={
                "cluster": "us_equity_beta",
                "routing_horizon": "swing",
            },
            test_allow_sleeve_overflow=True,
        )
        assert opened["ok"] is True

    _qualify_routes(
        desk,
        eligible={("mnq", "scalp")},
    )
    out = desk._allocate()
    assert not any(row.get("ok") for row in out)

    rows = [
        row
        for row in desk.opportunity_evaluations_snapshot(100)
        if row["asset_id"] == "mnq"
        and row["routing_horizon"] == "scalp"
    ]
    assert rows
    assert rows[0]["rejection_reason"] == (
        "cluster_risk_limit"
    )


def test_explicit_unopened_route_does_not_inherit_sibling_position():
    portfolio = PaperPortfolio(300_000.0)
    opened = portfolio.open_position(
        "nvda",
        side="long",
        quantity=10.0,
        price=180.0,
        stop_price=175.0,
        mode="scalp",
        position_key="nvda:scalp",
    )
    assert opened["ok"] is True
    assert portfolio.qty(
        "nvda",
        position_key="nvda:scalp",
    ) == 10.0
    assert portfolio.qty(
        "nvda",
        position_key="nvda:swing",
    ) == 0.0
    assert portfolio.position(
        "nvda",
        position_key="nvda:swing",
    ) is None
    assert portfolio.qty("nvda") == 10.0


def test_strategy_risk_policy_is_machine_visible_and_fixed_count_removed(monkeypatch):
    desk = _strategy_desk(monkeypatch, ())
    settings = desk.settings_snapshot()
    policy = settings["strategy_risk_policy"]

    assert policy["max_trade_risk_pct"] == 0.75
    assert policy["max_asset_risk_pct"] == 1.5
    assert policy["max_cluster_risk_pct"] == 2.25
    assert policy["max_portfolio_risk_pct"] == 3.0
    assert policy["fixed_strategy_position_limit"] is None
