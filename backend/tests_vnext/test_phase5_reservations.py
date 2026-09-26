from __future__ import annotations

import pytest

from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.reservations import reservation_requirement


def test_btc_long_reserve_matches_entry_fill_plus_entry_fee() -> None:
    row = SEED_REGISTRY["btc"]
    req = reservation_requirement(
        row,
        side="long",
        qty=0.01,
        bid=99_990.0,
        ask=100_010.0,
        modeled_round_trip_cost_pct=0.10,
    )
    expected_entry = 100_010.0 * 1.0005
    expected_fee = (0.01 * expected_entry) * 0.0026
    assert req.computed_entry_price == pytest.approx(expected_entry)
    assert req.entry_fee_usd == pytest.approx(expected_fee)
    assert req.margin_need_usd == 0.0
    assert req.reserve_cash_usd == pytest.approx(
        0.01 * expected_entry + expected_fee
    )


def test_eurusd_worked_example_reproduces_550_96_reserve() -> None:
    row = SEED_REGISTRY["eurusd"]
    notional = 0.10 * 100_000.0 * 1.08512
    modeled_pct = (8.40 / notional) * 100.0
    req = reservation_requirement(
        row,
        side="long",
        qty=0.10,
        bid=1.08500,
        ask=1.08512,
        modeled_round_trip_cost_pct=modeled_pct,
    )
    assert req.margin_need_usd == pytest.approx(542.56)
    assert req.estimated_cost_buffer_usd == pytest.approx(8.40)
    assert req.reserve_cash_usd == pytest.approx(550.96)


@pytest.mark.parametrize(
    ("asset_id", "expected_margin"),
    (
        ("mes", 1200.0),
        ("mnq", 1400.0),
        ("mgc", 1000.0),
        ("mcl", 1000.0),
        ("us10y", 800.0),
    ),
)
def test_seed_futures_margin_is_fixed_per_contract(
    asset_id: str,
    expected_margin: float,
) -> None:
    row = SEED_REGISTRY[asset_id]
    req = reservation_requirement(
        row,
        side="long",
        qty=1.0,
        bid=100.0,
        ask=100.25,
        modeled_round_trip_cost_pct=0.10,
    )
    assert req.margin_need_usd == pytest.approx(expected_margin)
    assert req.reserve_cash_usd > expected_margin


def test_equity_long_is_cash_purchase_plus_entry_fee() -> None:
    row = SEED_REGISTRY["nvda"]
    req = reservation_requirement(
        row,
        side="long",
        qty=10.0,
        bid=99.99,
        ask=100.00,
        modeled_round_trip_cost_pct=0.10,
    )
    expected_entry = 100.00 * 1.0005
    expected_fee = 1.0
    assert req.margin_need_usd == 0.0
    assert req.entry_fee_usd == pytest.approx(expected_fee)
    assert req.reserve_cash_usd == pytest.approx(
        10.0 * expected_entry + expected_fee
    )


def test_equity_short_reserves_half_notional_fee_and_one_day_borrow() -> None:
    row = SEED_REGISTRY["nvda"]
    req = reservation_requirement(
        row,
        side="short",
        qty=10.0,
        bid=100.00,
        ask=100.01,
        modeled_round_trip_cost_pct=0.10,
    )
    notional = 1_000.0
    expected_margin = 500.0
    expected_fee = 1.0 + notional * 0.000008
    expected_borrow = notional * 0.005 / 365.0
    assert req.margin_need_usd == pytest.approx(expected_margin)
    assert req.entry_fee_usd == pytest.approx(expected_fee)
    assert req.borrow_buffer_usd == pytest.approx(expected_borrow)
    assert req.reserve_cash_usd == pytest.approx(
        expected_margin + expected_fee + expected_borrow
    )


def test_spot_crypto_short_reserve_is_refused() -> None:
    with pytest.raises(ValueError, match="spot crypto short reserve is unsupported"):
        reservation_requirement(
            SEED_REGISTRY["btc"],
            side="short",
            qty=0.01,
            bid=100_000.0,
            ask=100_010.0,
            modeled_round_trip_cost_pct=0.10,
        )
