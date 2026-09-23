from datetime import datetime, timezone

import app.pair_book as pair_book_module
from app.desk import MultiDesk
from app.paper_portfolio import PaperPortfolio


def _desk(monkeypatch):
    from app import desk as desk_module

    monkeypatch.setattr(desk_module, "load_desk", lambda: None)
    desk = MultiDesk(execution_test_mode=False)
    desk.wallet = PaperPortfolio(300_000.0)
    for base in desk.books:
        base.wallet = desk.wallet
    for route_book in desk.route_books.values():
        route_book.wallet = desk.wallet
    return desk


def _open_route(
    desk,
    key,
    *,
    side="short",
    entry=100.0,
    stop=105.0,
):
    aid, horizon = key.split(":", 1)
    route = desk.route_books[key]
    route.mark = entry
    route.bid = entry - 0.01
    route.ask = entry + 0.01
    route.bars.clear()
    route.bars.append(
        {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "open": entry,
            "high": entry,
            "low": entry,
            "close": entry,
            "volume": 1.0,
        }
    )
    opened = desk.wallet.open_position(
        aid,
        side=side,
        quantity=1.0,
        price=entry,
        stop_price=stop,
        mode=horizon,
        position_key=key,
        metadata={
            "routing_horizon": horizon,
            "originating_horizon": horizon,
        },
    )
    assert opened["ok"] is True
    route.entry_at = opened["opened_at"]
    route.entry_mode = horizon
    route.stop = stop
    route.highest = entry
    route.lowest = entry
    return route, opened


def test_management_contract_keeps_scalp_intraday_and_swing_identity(monkeypatch):
    desk = _desk(monkeypatch)

    expected = {
        "nvda:scalp": ("scalp", "1m", 15),
        "nvda:intraday": ("intraday", "15m", 390),
        "nvda:swing": ("swing", "1h", 4320),
    }
    for key, (mode, clock, limit) in expected.items():
        route, _ = _open_route(desk, key)
        contract = route.management_contract()

        assert contract["originating_horizon"] == key.split(":", 1)[1]
        assert contract["management_mode"] == mode
        assert contract["management_clock"] == clock
        assert contract["time_stop_minutes"] == limit

        desk.wallet.close_position(
            "nvda",
            price=100.0,
            position_key=key,
        )


def test_crypto_swing_route_maps_to_daily_swing_management(monkeypatch):
    desk = _desk(monkeypatch)
    route = desk.route_books["btc:swing"]
    opened = desk.wallet.open_position(
        "btc",
        side="long",
        quantity=0.001,
        price=100_000.0,
        stop_price=95_000.0,
        mode="daily_swing",
        position_key="btc:swing",
        metadata={
            "routing_horizon": "swing",
            "originating_horizon": "swing",
        },
    )
    assert opened["ok"] is True
    route.entry_at = opened["opened_at"]
    route.entry_mode = "daily_swing"

    contract = route.management_contract()
    assert contract["originating_horizon"] == "swing"
    assert contract["management_mode"] == "daily_swing"
    assert contract["management_clock"] == "1d"
    assert contract["time_stop_minutes"] is None


def test_route_horizon_overrides_wrong_saved_entry_mode(monkeypatch):
    desk = _desk(monkeypatch)
    route, opened = _open_route(desk, "nvda:scalp")
    stored = desk.wallet.positions["nvda:scalp"]
    stored["mode"] = "swing"
    stored["metadata"]["routing_horizon"] = "swing"
    stored["metadata"]["originating_horizon"] = "swing"
    route.entry_mode = "swing"

    contract = route.management_contract()

    assert contract["originating_horizon"] == "scalp"
    assert contract["management_mode"] == "scalp"
    assert contract["management_clock"] == "1m"
    assert contract["source"] == "route_horizon"


def test_manage_requests_originating_horizon_playbook(monkeypatch):
    desk = _desk(monkeypatch)

    for key, expected_mode in (
        ("nvda:scalp", "scalp"),
        ("nvda:intraday", "intraday"),
        ("nvda:swing", "swing"),
    ):
        route, _ = _open_route(desk, key)
        calls = []

        def snapshot_strategy(**kwargs):
            calls.append(kwargs.get("requested_mode"))
            return {
                "risk_stop_pct": 2.0,
                "cost_pct": 0.0,
                "exit_signal": None,
            }

        monkeypatch.setattr(
            route,
            "snapshot_strategy",
            snapshot_strategy,
        )
        result = route.manage()

        assert result is None
        assert calls == [expected_mode]
        assert desk.wallet.position(
            "nvda",
            position_key=key,
        ) is not None

        desk.wallet.close_position(
            "nvda",
            price=100.0,
            position_key=key,
        )


def test_sibling_horizons_manage_stops_independently(monkeypatch):
    desk = _desk(monkeypatch)
    scalp, _ = _open_route(
        desk,
        "nvda:scalp",
        entry=100.0,
        stop=110.0,
    )
    swing, _ = _open_route(
        desk,
        "nvda:swing",
        entry=100.0,
        stop=120.0,
    )

    scalp.mark = 90.0
    scalp.bid = 89.99
    scalp.ask = 90.01
    scalp.lowest = 90.0
    scalp.bars.clear()
    scalp.bars.append(
        {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "open": 90.0,
            "high": 90.0,
            "low": 90.0,
            "close": 90.0,
            "volume": 1.0,
        }
    )
    swing.mark = 100.0

    monkeypatch.setattr(
        scalp,
        "snapshot_strategy",
        lambda **_kwargs: {
            "risk_stop_pct": 2.0,
            "cost_pct": 0.0,
            "exit_signal": None,
        },
    )

    before_swing_stop = swing.stop
    result = scalp.manage()

    assert result is None
    assert scalp.stop < 110.0
    assert swing.stop == before_swing_stop
    assert desk.wallet.position(
        "nvda",
        position_key="nvda:scalp",
    )["current_stop"] == scalp.stop
    assert desk.wallet.position(
        "nvda",
        position_key="nvda:swing",
    )["current_stop"] == before_swing_stop


def test_restart_preserves_route_management_contract(monkeypatch):
    desk = _desk(monkeypatch)
    route, opened = _open_route(
        desk,
        "nvda:intraday",
        entry=100.0,
        stop=95.0,
    )
    route.highest = 104.0
    route.lowest = 98.0

    state = {
        "wallet": desk.wallet.payload(),
        "books": {},
        "route_books": {
            key: {
                "stop": book.stop,
                "highest": book.highest,
                "lowest": book.lowest,
                "entry_at": book.entry_at,
                "entry_mode": book.entry_mode,
                "last_entry_signal_key": (
                    book.last_entry_signal_key
                ),
                "last_reason": book.last_reason,
                "fills": list(book.fills),
            }
            for key, book in desk.route_books.items()
        },
    }

    restored = _desk(monkeypatch)
    restored._restore(state)
    restored_route = restored.route_books[
        "nvda:intraday"
    ]
    contract = restored_route.management_contract()

    assert restored.wallet.position(
        "nvda",
        position_key="nvda:intraday",
    )["trade_id"] == opened["trade_id"]
    assert restored_route.stop == 95.0
    assert restored_route.highest == 104.0
    assert restored_route.lowest == 98.0
    assert contract["originating_horizon"] == "intraday"
    assert contract["management_mode"] == "intraday"
    assert contract["management_clock"] == "15m"
    assert contract["time_stop_minutes"] == 390


def test_execution_validation_management_stays_on_valid_primary_playbook(monkeypatch):
    desk = _desk(monkeypatch)
    base = desk.by_id["mes"]
    base.mark = 6000.0
    base.bid = 5999.75
    base.ask = 6000.25
    opened = desk.wallet.open_position(
        "mes",
        side="long",
        quantity=1.0,
        price=6000.0,
        stop_price=5900.0,
        mode="execution_test",
        position_key="mes",
        execution_test=True,
        metadata={
            "execution_test": True,
            "execution_test_load": "AETHER-LOAD-002",
        },
    )
    assert opened["ok"] is True
    base.entry_at = opened["opened_at"]
    base.entry_mode = "execution_test"

    contract = base.management_contract()

    assert contract["execution_test"] is True
    assert contract["management_mode"] == "intraday"
    assert contract["source"] == "execution_validation_primary"
