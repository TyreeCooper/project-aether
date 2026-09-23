from app.desk import MultiDesk
from app.execution_matrix import (
    ASSET_HORIZONS,
    MATRIX_HORIZONS,
    capability_cells,
    directional_summary,
    forced_execution_snapshot,
)
from app.paper_portfolio import PaperPortfolio


def test_directional_matrix_has_12_long_and_10_short_capable_assets():
    summary = directional_summary()
    assert summary["long_supported_count"] == 12
    assert summary["short_supported_count"] == 10
    assert set(summary["short_supported_assets"]) == {
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
    }


def test_matrix_reports_unsupported_cells_as_na_instead_of_fabricating_them():
    rows = capability_cells()
    assert len(rows) == 12 * len(MATRIX_HORIZONS) * 2
    btc_short = [
        row for row in rows
        if row["asset_id"] == "btc" and row["side"] == "short"
    ]
    eth_short = [
        row for row in rows
        if row["asset_id"] == "eth" and row["side"] == "short"
    ]
    assert btc_short and eth_short
    assert all(row["status"] == "n/a" for row in btc_short + eth_short)
    assert all(
        row["reason"] == "side_not_supported_by_product"
        or row["reason"] == "horizon_not_configured_for_asset"
        for row in btc_short + eth_short
    )


def test_asset_horizon_contract_is_explicit():
    assert ASSET_HORIZONS["eurusd"] == ("scalp", "intraday", "swing")
    assert ASSET_HORIZONS["mes"] == ("scalp", "intraday", "swing")
    assert ASSET_HORIZONS["mgc"] == ("intraday", "swing")
    assert ASSET_HORIZONS["us10y"] == ("swing",)
    assert ASSET_HORIZONS["btc"] == ("swing",)


def test_forced_snapshot_refuses_unsupported_product_side():
    try:
        forced_execution_snapshot("btc", "swing", "short")
    except ValueError as exc:
        assert str(exc) == "side_not_supported_by_product"
    else:
        raise AssertionError("BTC spot short must remain unsupported")


def test_all_ten_supported_short_books_execute_actual_short_positions():
    desk = MultiDesk(execution_test_mode=True)
    desk.wallet = PaperPortfolio(500_000.0)
    short_assets = set(directional_summary()["short_supported_assets"])

    for book in desk.books:
        book.wallet = desk.wallet
        book.mark = 100.0
        book.bid = 99.9
        book.ask = 100.1
        book.fills = []
        if book.id not in short_assets:
            continue
        horizon = ASSET_HORIZONS[book.id][0]
        snap = forced_execution_snapshot(
            book.id,
            horizon,
            "short",
            baseline={
                "reason": "normal_gate_blocked",
                "execution_status": "waiting",
                "quality_score": 25,
            },
        )
        result = book.enter(
            100.0,
            strategy_snapshot=snap,
            max_capital_usd=None,
            execution_test=True,
        )
        assert result["ok"] is True, (book.id, result)
        assert result["position_side"] == "short"
        pos = desk.wallet.position(book.id)
        assert pos is not None
        assert pos["side"] == "short"
        assert pos["metadata"]["matrix_side"] == "short"
        assert pos["metadata"]["matrix_horizon"] == horizon

    assert {
        aid for aid, pos in desk.wallet.positions.items()
        if pos["side"] == "short"
    } == short_assets


def test_execution_matrix_snapshot_is_read_only_capability_contract():
    desk = MultiDesk(execution_test_mode=True)
    snap = desk.execution_matrix_snapshot()
    assert snap["load"] == "AETHER-LOAD-002"
    assert snap["long_supported_count"] == 12
    assert snap["short_supported_count"] == 10
    assert snap["cells"]
