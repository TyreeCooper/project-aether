from __future__ import annotations

import pytest

from aether_vnext.equity import (
    consolidated_equity_usd,
    conservative_mark_price,
    conservative_unrealized_pnl_usd,
    inventory_market_value_usd,
    sleeve_equity_projection,
)
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.reservations import reservation_requirement


def test_seed_sleeves_consolidate_to_exactly_10000_before_trading() -> None:
    rows = (
        sleeve_equity_projection(
            broker_account_id="kraken_paper",
            cash_available_usd=4000.0,
            cash_reserved_usd=0.0,
            cash_inventory_backing_reserve_usd=0.0,
            inventory_mtm_usd=0.0,
            non_inventory_unrealized_pnl_usd=0.0,
            fees_accrued_usd=0.0,
        ),
        sleeve_equity_projection(
            broker_account_id="tastyfx_paper",
            cash_available_usd=2000.0,
            cash_reserved_usd=0.0,
            cash_inventory_backing_reserve_usd=0.0,
            inventory_mtm_usd=0.0,
            non_inventory_unrealized_pnl_usd=0.0,
            fees_accrued_usd=0.0,
        ),
        sleeve_equity_projection(
            broker_account_id="ninja_paper",
            cash_available_usd=2000.0,
            cash_reserved_usd=0.0,
            cash_inventory_backing_reserve_usd=0.0,
            inventory_mtm_usd=0.0,
            non_inventory_unrealized_pnl_usd=0.0,
            fees_accrued_usd=0.0,
        ),
        sleeve_equity_projection(
            broker_account_id="ibkr_paper",
            cash_available_usd=2000.0,
            cash_reserved_usd=0.0,
            cash_inventory_backing_reserve_usd=0.0,
            inventory_mtm_usd=0.0,
            non_inventory_unrealized_pnl_usd=0.0,
            fees_accrued_usd=0.0,
        ),
    )
    assert consolidated_equity_usd(rows) == pytest.approx(10_000.0)


def test_btc_cash_inventory_does_not_double_count_purchase_reserve() -> None:
    req = reservation_requirement(
        SEED_REGISTRY["btc"],
        side="long",
        qty=0.01,
        bid=99_990.0,
        ask=100_010.0,
        modeled_round_trip_cost_pct=0.10,
    )
    cash_available = 4000.0 - req.reserve_cash_usd
    inventory_mtm = inventory_market_value_usd(
        quantity=0.01,
        conservative_bid=101_000.0,
    )

    projection = sleeve_equity_projection(
        broker_account_id="kraken_paper",
        cash_available_usd=cash_available,
        cash_reserved_usd=req.reserve_cash_usd,
        cash_inventory_backing_reserve_usd=req.reserve_cash_usd,
        inventory_mtm_usd=inventory_mtm,
        non_inventory_unrealized_pnl_usd=0.0,
        fees_accrued_usd=0.0,
    )

    expected = cash_available + inventory_mtm
    assert projection.sleeve_equity_usd == pytest.approx(expected)

    literal_double_count = (
        cash_available
        + req.reserve_cash_usd
        + inventory_mtm
    )
    assert projection.sleeve_equity_usd < literal_double_count


def test_pending_reserve_remains_equity_while_inventory_backing_is_removed_once() -> None:
    inventory_reserve = 1000.0
    pending_order_reserve = 125.0
    projection = sleeve_equity_projection(
        broker_account_id="kraken_paper",
        cash_available_usd=2875.0,
        cash_reserved_usd=inventory_reserve + pending_order_reserve,
        cash_inventory_backing_reserve_usd=inventory_reserve,
        inventory_mtm_usd=1025.0,
        non_inventory_unrealized_pnl_usd=0.0,
        fees_accrued_usd=0.0,
    )
    assert projection.sleeve_equity_usd == pytest.approx(
        2875.0 + pending_order_reserve + 1025.0
    )


def test_margin_reserve_stays_capital_and_margin_is_not_subtracted_twice() -> None:
    req = reservation_requirement(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        bid=1.08500,
        ask=1.08512,
        modeled_round_trip_cost_pct=(8.40 / 10851.20) * 100.0,
    )
    unrealized = conservative_unrealized_pnl_usd(
        SEED_REGISTRY["eurusd"],
        side="long",
        quantity=0.10,
        avg_entry_price=req.computed_entry_price,
        bid=1.08600,
        ask=1.08612,
    )
    projection = sleeve_equity_projection(
        broker_account_id="tastyfx_paper",
        cash_available_usd=2000.0 - req.reserve_cash_usd,
        cash_reserved_usd=req.reserve_cash_usd,
        cash_inventory_backing_reserve_usd=0.0,
        inventory_mtm_usd=0.0,
        non_inventory_unrealized_pnl_usd=unrealized,
        fees_accrued_usd=0.0,
    )
    assert projection.sleeve_equity_usd == pytest.approx(2000.0 + unrealized)


def test_conservative_marks_use_bid_for_long_and_ask_for_short() -> None:
    assert conservative_mark_price(
        side="long",
        bid=99.0,
        ask=101.0,
    ) == 99.0
    assert conservative_mark_price(
        side="short",
        bid=99.0,
        ask=101.0,
    ) == 101.0


def test_short_equity_unrealized_marks_against_ask() -> None:
    pnl = conservative_unrealized_pnl_usd(
        SEED_REGISTRY["nvda"],
        side="short",
        quantity=10.0,
        avg_entry_price=100.0,
        bid=94.0,
        ask=95.0,
    )
    assert pnl == pytest.approx(50.0)


def test_inventory_backing_cannot_exceed_reserved_cash() -> None:
    with pytest.raises(
        ValueError,
        match="inventory backing reserve cannot exceed cash_reserved_usd",
    ):
        sleeve_equity_projection(
            broker_account_id="kraken_paper",
            cash_available_usd=3000.0,
            cash_reserved_usd=900.0,
            cash_inventory_backing_reserve_usd=1000.0,
            inventory_mtm_usd=1000.0,
            non_inventory_unrealized_pnl_usd=0.0,
            fees_accrued_usd=0.0,
        )


def test_consolidated_projection_rejects_duplicate_sleeve_identity() -> None:
    row = sleeve_equity_projection(
        broker_account_id="kraken_paper",
        cash_available_usd=4000.0,
        cash_reserved_usd=0.0,
        cash_inventory_backing_reserve_usd=0.0,
        inventory_mtm_usd=0.0,
        non_inventory_unrealized_pnl_usd=0.0,
        fees_accrued_usd=0.0,
    )
    with pytest.raises(
        ValueError,
        match="duplicate broker_account_id",
    ):
        consolidated_equity_usd((row, row))
