from app import desk as desk_module
from app.desk import (
    DEFAULT_TRADE_FILTER_SETTINGS,
    LOCKED_TRADE_FILTERS,
    OPTIONAL_TRADE_FILTERS,
    MultiDesk,
)
from app.horizons import TradingHorizon
from app.pair_book import PairBook
from app.paper_portfolio import PaperPortfolio
from app.playbooks import playbook_snapshot
from app.routing import ROUTES
from app.universe import BY_ID


def _daily(count=240, start=100.0, step=1.0):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_650_000_000 + i * 86400,
                "open": px - step / 2,
                "high": px + abs(step) * 0.25 + 0.01,
                "low": px - abs(step) * 0.25 - 0.01,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def _hourly(count=240, start=100.0, step=0.25):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_700_000_000 + i * 3600,
                "open": px - step / 2,
                "high": px + abs(step) * 0.20 + 0.01,
                "low": px - abs(step) * 0.20 - 0.01,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def _minutes(count=900, start=100.0, step=0.02):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_700_000_000 + i * 60,
                "open": px - step / 2,
                "high": px + abs(step) * 0.20 + 0.001,
                "low": px - abs(step) * 0.20 - 0.001,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def _desk(monkeypatch):
    monkeypatch.setattr(
        desk_module,
        "load_desk",
        lambda: None,
    )
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    desk.armed = True
    desk.persist = lambda: None
    monkeypatch.setattr(
        desk,
        "_btc_gate",
        lambda: (True, False),
    )
    monkeypatch.setattr(
        desk,
        "_latest_closed_minute_ts",
        lambda: 1_700_000_060,
    )
    for base in desk.books:
        base.wallet = desk.wallet
        base.mark = 100.0
        base.bid = 99.99
        base.ask = 100.01
        base.bars.clear()
        base.bars.append(
            {
                "ts": 1_700_000_000,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
            }
        )
        desk._sync_asset_route_books(base.id)
    for route in desk.route_books.values():
        route.wallet = desk.wallet
    return desk


def test_filter_settings_default_to_current_aether_behavior(monkeypatch):
    desk = _desk(monkeypatch)
    snap = desk.settings_snapshot()["trade_filters"]

    assert snap["optional_total"] == len(
        OPTIONAL_TRADE_FILTERS
    )
    assert snap["optional_enabled"] == len(
        OPTIONAL_TRADE_FILTERS
    )
    assert all(
        row["enabled"]
        for row in snap["optional"].values()
    )
    assert len(snap["locked"]) == len(
        LOCKED_TRADE_FILTERS
    )
    assert all(
        row["enabled"] and row["locked"]
        for row in snap["locked"].values()
    )
    assert snap["special_mode"] is False
    assert snap["forced_entries_enabled"] is False


def test_filter_settings_persist_and_restore_without_runtime_mode_change(
    monkeypatch,
):
    saved = []
    monkeypatch.setattr(
        desk_module,
        "load_desk",
        lambda: None,
    )
    monkeypatch.setattr(
        desk_module,
        "save_desk",
        lambda payload: saved.append(payload),
    )

    desk = MultiDesk(execution_test_mode=False)
    changed = dict(DEFAULT_TRADE_FILTER_SETTINGS)
    changed["session_window"] = False
    changed["cost_edge_hurdle"] = False
    changed["quality_ranking"] = False
    desk.update_settings(
        allocation_per_entry_pct=8.0,
        quote_poll_seconds=20,
        trade_filters=changed,
    )

    assert saved
    persisted = saved[-1]
    assert (
        persisted["settings"]["trade_filters"]
        ["session_window"]
        is False
    )
    assert (
        persisted["settings"]["trade_filters"]
        ["cost_edge_hurdle"]
        is False
    )

    monkeypatch.setattr(
        desk_module,
        "load_desk",
        lambda: persisted,
    )
    restored = MultiDesk(execution_test_mode=False)
    assert restored.trade_filters["session_window"] is False
    assert restored.trade_filters["cost_edge_hurdle"] is False
    assert restored.trade_filters["quality_ranking"] is False
    assert restored.runtime_mode() == "strategy_test"
    assert restored.execution_test_mode is False


def test_session_filter_can_be_bypassed_without_forcing_direction():
    daily = _daily(100, start=50.0, step=0.5)
    hourly = _hourly(240, start=80.0, step=0.25)
    minute = _minutes(900, start=120.0, step=0.03)

    blocked = playbook_snapshot(
        "nvda",
        minute,
        hourly,
        daily,
        mark=minute[-1]["close"],
        active_session_ids={"premarket"},
        requested_mode="intraday",
    )
    assert blocked["signal"] is None
    assert blocked["reason"] == "session_closed"

    allowed = playbook_snapshot(
        "nvda",
        minute,
        hourly,
        daily,
        mark=minute[-1]["close"],
        active_session_ids={"premarket"},
        requested_mode="intraday",
        filter_settings={"session_window": False},
    )
    assert allowed["signal"] == "buy"
    assert allowed["executable_signal"] == "buy"
    assert (
        allowed["filter_trace"]["session_window"]
        == "bypassed"
    )
    assert (
        allowed["filter_trace"]["direction_required"]
        == "passed"
    )


def test_continuation_filter_bypass_still_requires_direction():
    daily = _daily(100, start=50.0, step=0.5)
    hourly = _hourly(240, start=80.0, step=0.25)
    minute = _minutes(900, start=120.0, step=0.0)

    blocked = playbook_snapshot(
        "nvda",
        minute,
        hourly,
        daily,
        mark=120.0,
        active_session_ids={"rth"},
        requested_mode="intraday",
    )
    assert blocked["signal"] is None
    assert blocked["reason"] == "no_15m_continuation"

    allowed = playbook_snapshot(
        "nvda",
        minute,
        hourly,
        daily,
        mark=120.0,
        active_session_ids={"rth"},
        requested_mode="intraday",
        filter_settings={
            "continuation_trigger": False,
        },
    )
    assert allowed["signal"] == "buy"
    assert (
        allowed["filter_trace"]["continuation_trigger"]
        == "bypassed"
    )
    assert (
        allowed["filter_trace"]["direction_required"]
        == "passed"
    )


def test_eth_btc_rider_can_be_bypassed_but_breakout_direction_cannot():
    bars = _daily(240, step=1.0)

    blocked = playbook_snapshot(
        "eth",
        [],
        [],
        bars,
        mark=bars[-1]["close"],
        btc_bias_on=True,
        btc_in_position=False,
    )
    assert blocked["signal"] is None
    assert blocked["reason"] == "btc_rider_gate_closed"

    allowed = playbook_snapshot(
        "eth",
        [],
        [],
        bars,
        mark=bars[-1]["close"],
        btc_bias_on=True,
        btc_in_position=False,
        filter_settings={"crypto_btc_rider": False},
    )
    assert allowed["signal"] == "buy"
    assert (
        allowed["filter_trace"]["crypto_btc_rider"]
        == "bypassed"
    )
    assert (
        allowed["filter_trace"]["crypto_breakout_direction"]
        == "passed"
    )


def test_cost_edge_filter_can_be_bypassed_without_bypassing_risk_sizing():
    wallet = PaperPortfolio(300_000.0)
    book = PairBook(BY_ID["nvda"], wallet)
    book.mark = 100.0
    book.bid = 99.0
    book.ask = 101.0

    blocked = book.entry_plan(
        2_250.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "scalp",
            "risk_stop_pct": 2.0,
            "position_key": "nvda:scalp",
            "opportunity_pct": 1.0,
        },
        max_capital_usd=24_000.0,
    )
    assert blocked["ok"] is False
    assert blocked["error"] == "edge_below_cost_hurdle"

    allowed = book.entry_plan(
        2_250.0,
        strategy_snapshot={
            "executable_signal": "buy",
            "mode": "scalp",
            "risk_stop_pct": 2.0,
            "position_key": "nvda:scalp",
            "opportunity_pct": 1.0,
            "trade_filter_settings": {
                "cost_edge_hurdle": False,
            },
        },
        max_capital_usd=24_000.0,
    )
    assert allowed["ok"] is True
    assert allowed["cost_edge_filter_status"] == "bypassed"
    assert allowed["stop_risk_usd"] <= 2_250.0 + 1e-6


def test_route_clock_off_evaluates_all_supported_routes_without_forcing_trade(
    monkeypatch,
):
    desk = _desk(monkeypatch)
    desk.trade_filters["route_clock"] = False
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: (),
    )

    calls = []
    for route in desk.route_books.values():

        def snapshot_strategy(
            *,
            btc_bias_on=False,
            btc_in_position=False,
            requested_mode=None,
            _book=route,
        ):
            calls.append(
                (_book.id, _book.routing_horizon)
            )
            return {
                "signal": None,
                "executable_signal": None,
                "mode": requested_mode,
                "reason": "no_setup",
                "execution_status": "no_trade",
                "quality_score": 0,
            }

        route.snapshot_strategy = snapshot_strategy

    assert desk._allocate() == []
    assert len(calls) == 28
    assert desk.wallet.positions == {}
    traffic = desk.trade_filter_snapshot()["traffic"]
    assert traffic["route_clock"]["bypassed"] == 28


def test_all_optional_filters_off_still_cannot_create_trade_without_direction(
    monkeypatch,
):
    desk = _desk(monkeypatch)
    for key in desk.trade_filters:
        desk.trade_filters[key] = False
    monkeypatch.setattr(
        desk.strategy_router,
        "due",
        lambda _ts: (
            ROUTES[TradingHorizon.SCALP],
            ROUTES[TradingHorizon.INTRADAY],
            ROUTES[TradingHorizon.SWING],
            ROUTES[TradingHorizon.POSITION],
        ),
    )

    for route in desk.route_books.values():
        route.snapshot_strategy = lambda **_kwargs: {
            "signal": None,
            "executable_signal": None,
            "mode": "scalp",
            "reason": "no_direction",
            "execution_status": "no_trade",
            "quality_score": 0,
            "filter_trace": {
                "direction_required": "rejected",
            },
        }

    assert desk._allocate() == []
    assert desk.wallet.positions == {}
    assert (
        desk.trade_filter_snapshot()["traffic"]
        ["direction_required"]["rejected"]
        > 0
    )
