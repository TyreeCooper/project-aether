from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone

import pytest

from aether_vnext.calendars import (
    CalendarDecision,
    CalendarException,
    CalendarExceptionKind,
    calendar_decision,
)
from aether_vnext.costs import (
    IBKR_SEC_SELL_RATE,
    KRAKEN_TAKER_BPS,
    modeled_round_trip_cost,
    notional_usd,
    ready_after_cost_hurdle,
)
from aether_vnext.registry import (
    BindingState,
    LifecycleState,
    LiveAdapterStatus,
    SEED_REGISTRY,
    bind_futures_contract,
    bind_market_data,
    validate_registry_row,
)


UTC = timezone.utc


class StaticExceptions:
    def __init__(self, mapping: dict[tuple[str, date], CalendarException]):
        self.mapping = mapping

    def exception_for(self, *, calendar_id: str, session_date: date):
        return self.mapping.get((calendar_id, session_date)) or CalendarException(
            calendar_id=calendar_id,
            session_date=session_date,
            kind=CalendarExceptionKind.NORMAL,
        )


def test_seed_registry_has_exactly_twelve_rows_and_no_schema_errors() -> None:
    assert len(SEED_REGISTRY) == 12
    for row in SEED_REGISTRY.values():
        assert validate_registry_row(row) == ()
        assert row.live_adapter_status is LiveAdapterStatus.NOT_AUTHORIZED
        assert "live_hard_blocked" in row.venue_constraints


def test_crypto_side_truth_is_long_only_and_short_not_supported() -> None:
    btc = SEED_REGISTRY["btc"]
    eth = SEED_REGISTRY["eth"]
    assert btc.product_side_supported("long") is True
    assert btc.product_side_supported("short") is False
    assert eth.product_side_supported("short") is False


def test_equity_short_requires_available_shortability_and_locate() -> None:
    nvda = SEED_REGISTRY["nvda"]
    assert nvda.product_side_supported("short", locate_ok=False) is False

    available = replace(nvda, shortability_state=nvda.shortability_state.AVAILABLE)
    assert available.product_side_supported("short", locate_ok=False) is False
    assert available.product_side_supported("short", locate_ok=True) is True


def test_nonkraken_data_bindings_are_explicitly_unbound_not_invented() -> None:
    assert SEED_REGISTRY["eurusd"].market_data_binding_state is BindingState.UNBOUND
    assert SEED_REGISTRY["mes"].market_data_binding_state is BindingState.UNBOUND
    assert SEED_REGISTRY["nvda"].market_data_binding_state is BindingState.UNBOUND


def test_market_binding_requires_explicit_source_and_stale_threshold() -> None:
    row = SEED_REGISTRY["eurusd"]
    bound = bind_market_data(
        row,
        primary_source_id="test.provider",
        stale_threshold_ms=1500,
    )
    assert bound.market_data_ready() is True
    assert bound.primary_market_source_id == "test.provider"
    assert bound.stale_threshold_ms == 1500
    with pytest.raises(ValueError):
        bind_market_data(row, primary_source_id="", stale_threshold_ms=1500)
    with pytest.raises(ValueError):
        bind_market_data(row, primary_source_id="x", stale_threshold_ms=0)


def test_futures_cannot_fire_until_exact_current_contract_and_expiry_are_bound() -> None:
    mes = SEED_REGISTRY["mes"]
    now = datetime(2026, 9, 26, 12, tzinfo=UTC)
    assert mes.lifecycle_fire_eligible(now) is False

    bound = bind_futures_contract(
        mes,
        current_contract="MESZ26",
        expiry_utc=datetime(2026, 12, 18, 14, 30, tzinfo=UTC),
        next_contract="MESH27",
    )
    assert bound.futures_lifecycle is not None
    assert bound.futures_lifecycle.roll_cutoff_hours_before_expiry == 48
    assert bound.futures_lifecycle.automatic_roll_allowed is False
    assert bound.lifecycle_fire_eligible(now) is True


def test_futures_fire_is_blocked_at_and_after_48h_roll_cutoff() -> None:
    row = bind_futures_contract(
        SEED_REGISTRY["us10y"],
        current_contract="ZNZ26",
        expiry_utc=datetime(2026, 12, 21, 14, 0, tzinfo=UTC),
        next_contract="ZNH27",
    )
    cutoff = datetime(2026, 12, 19, 14, 0, tzinfo=UTC)
    assert row.lifecycle_fire_eligible(cutoff) is False
    assert row.lifecycle_fire_eligible(
        datetime(2026, 12, 19, 13, 59, 59, tzinfo=UTC)
    ) is True


def test_noncrypto_calendar_refuses_to_invent_holiday_state() -> None:
    monday = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
    decision = calendar_decision(
        calendar_id="us_rth",
        at_utc=monday,
        exception_provider=None,
    )
    assert decision.eligible is False
    assert decision.reason == "calendar_exception_provider_required"


def test_crypto_calendar_is_24x7_without_holiday_provider() -> None:
    when = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)
    decision = calendar_decision(
        calendar_id="crypto_24x7",
        at_utc=when,
        exception_provider=None,
    )
    assert decision.eligible is True
    assert decision.focus is True


def test_us_rth_early_close_is_authoritative_from_provider() -> None:
    when = datetime(2026, 11, 27, 17, 30, tzinfo=UTC)  # 12:30 ET
    provider = StaticExceptions(
        {
            ("us_rth", date(2026, 11, 27)): CalendarException(
                calendar_id="us_rth",
                session_date=date(2026, 11, 27),
                kind=CalendarExceptionKind.EARLY_CLOSE,
                early_close_et=time(13, 0),
            )
        }
    )
    decision = calendar_decision(
        calendar_id="us_rth",
        at_utc=when,
        exception_provider=provider,
    )
    assert decision.eligible is True
    assert decision.session_end_et == time(13, 0)


def test_fx_rollover_window_is_maintenance() -> None:
    # 17:01 ET = 21:01 UTC while EDT is active.
    when = datetime(2026, 9, 28, 21, 1, tzinfo=UTC)
    decision = calendar_decision(
        calendar_id="fx_otc",
        at_utc=when,
        exception_provider=StaticExceptions({}),
    )
    assert decision.eligible is False
    assert decision.reason == "fx_rollover"


def test_kraken_fee_uses_26bps_per_leg_not_legacy_80bps() -> None:
    btc = SEED_REGISTRY["btc"]
    costs = modeled_round_trip_cost(
        btc,
        qty=0.01,
        entry_price=100_000.0,
        exit_reference_price=101_000.0,
        spread_abs=10.0,
        entry_side="buy",
        exit_side="sell",
    )
    expected_entry_fee = 1000.0 * (KRAKEN_TAKER_BPS / 10_000.0)
    assert costs.entry_fee_usd == pytest.approx(expected_entry_fee)
    assert costs.entry_fee_usd == pytest.approx(2.6)


def test_usdjpy_notional_and_quote_costs_convert_to_usd() -> None:
    row = SEED_REGISTRY["usdjpy"]
    assert notional_usd(row, qty=0.01, price=150.0) == pytest.approx(1000.0)
    costs = modeled_round_trip_cost(
        row,
        qty=0.01,
        entry_price=150.0,
        exit_reference_price=150.0,
        spread_abs=0.02,
        entry_side="buy",
        exit_side="sell",
    )
    # Spread = 0.02 JPY * 1000 USD base units / 150 JPY per USD.
    assert costs.spread_usd == pytest.approx(0.1333333333)


def test_ninja_fee_is_fifty_cents_per_side_per_contract() -> None:
    mes = SEED_REGISTRY["mes"]
    costs = modeled_round_trip_cost(
        mes,
        qty=1,
        entry_price=5000.0,
        exit_reference_price=5001.0,
        spread_abs=0.25,
        entry_side="buy",
        exit_side="sell",
    )
    assert costs.entry_fee_usd == pytest.approx(0.50)
    assert costs.exit_fee_usd == pytest.approx(0.50)


def test_ibkr_sell_leg_adds_sec_fee_and_short_borrow_default() -> None:
    nvda = SEED_REGISTRY["nvda"]
    costs = modeled_round_trip_cost(
        nvda,
        qty=100,
        entry_price=100.0,
        exit_reference_price=101.0,
        spread_abs=0.02,
        entry_side="buy",
        exit_side="sell",
        holding_days=0.0,
    )
    assert costs.entry_fee_usd == pytest.approx(1.0)
    assert costs.exit_fee_usd == pytest.approx(
        1.0 + (101.0 * 100.0 * IBKR_SEC_SELL_RATE)
    )

    short_costs = modeled_round_trip_cost(
        nvda,
        qty=100,
        entry_price=100.0,
        exit_reference_price=99.0,
        spread_abs=0.02,
        entry_side="sell",
        exit_side="buy",
        holding_days=10,
    )
    assert short_costs.carry_or_borrow_usd > 0


def test_ready_cost_hurdle_is_strictly_greater_than() -> None:
    btc = SEED_REGISTRY["btc"]
    costs = modeled_round_trip_cost(
        btc,
        qty=0.01,
        entry_price=100_000.0,
        exit_reference_price=100_000.0,
        spread_abs=0.0,
        entry_side="buy",
        exit_side="sell",
    )
    assert ready_after_cost_hurdle(
        opportunity_pct=costs.cost_hurdle_pct,
        costs=costs,
    ) is False
    assert ready_after_cost_hurdle(
        opportunity_pct=costs.cost_hurdle_pct + 1e-9,
        costs=costs,
    ) is True


def test_cost_edge_multiple_cannot_drop_below_one() -> None:
    btc = SEED_REGISTRY["btc"]
    with pytest.raises(ValueError):
        modeled_round_trip_cost(
            btc,
            qty=0.01,
            entry_price=100_000.0,
            exit_reference_price=100_000.0,
            spread_abs=0.0,
            entry_side="buy",
            exit_side="sell",
            cost_edge_multiple=0.99,
        )
