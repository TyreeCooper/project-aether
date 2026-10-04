from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.market_truth_contract import ExecutionState, ProviderRole
from aether_vnext.market_truth_execution import (
    PaperExecutionPolicy,
    assert_execution_fact_matches_book,
    execute_paper_against_route_book,
)
from aether_vnext.market_truth_fabric import ExecutableBookSnapshot
from aether_vnext.market_truth_provider import ProviderCard, ProviderCardRegistry, ProviderFeeSchedule
from aether_vnext.market_truth_route import RouteRecord


NOW = datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc)


def _route() -> RouteRecord:
    return RouteRecord("btc-usd", "kraken", (), "operator", NOW, 1)


def _providers(fee_bps: float | None = 26.0) -> ProviderCardRegistry:
    return ProviderCardRegistry((
        ProviderCard(
            "kraken",
            ProviderRole.BOTH,
            "Kraken",
            ProviderFeeSchedule("kraken_spot_taker_v1", taker_bps=fee_bps),
            "public_market_data;paper_execution_only;live_not_authorized",
        ),
    ))


def _book(state=ExecutionState.EXECUTABLE, *, ask_size=2.0, bid_size=2.0):
    values = dict(
        canonical_instrument_id="btc-usd",
        route_id=_route().route_id,
        executable_provider_id="kraken",
        venue="Kraken",
        transport_id="kraken-ws",
        state=state,
        bid=100.0,
        ask=101.0,
        last_if_printed=100.4,
        bid_size=bid_size,
        ask_size=ask_size,
        venue_time_utc=NOW,
        receive_time_utc=NOW,
        state_reason="fresh",
    )
    if state is not ExecutionState.EXECUTABLE:
        values.update(bid=None, ask=None, last_if_printed=None, bid_size=None, ask_size=None)
    return ExecutableBookSnapshot(**values)


POLICY = PaperExecutionPolicy(
    policy_version="first-proof-l1-v1",
    modeled_latency_ms=0,
    max_participation=1.0,
    l1_quantity_cap=10.0,
)


def test_buy_fill_uses_route_ask_and_provider_card_fee_only() -> None:
    fact = execute_paper_against_route_book(
        route=_route(), book=_book(), providers=_providers(),
        side="BUY", quantity=1.0, policy=POLICY,
    )
    assert fact.fill.accepted is True
    assert fact.fill.average_price == 101.0
    assert fact.fill.fee_usd == pytest.approx(101.0 * 26.0 / 10_000.0)
    assert fact.fee_schedule_id == "kraken_spot_taker_v1"
    assert fact.live_execution_authorized is False
    assert_execution_fact_matches_book(fact, _book())


def test_sell_fill_uses_route_bid_not_mid_or_last() -> None:
    fact = execute_paper_against_route_book(
        route=_route(), book=_book(), providers=_providers(),
        side="SELL", quantity=1.0, policy=POLICY,
    )
    assert fact.fill.accepted is True
    assert fact.fill.average_price == 100.0
    assert fact.fill.average_price != 100.5
    assert fact.fill.average_price != 100.4


def test_missing_provider_card_fee_rejects_instead_of_inventing_number() -> None:
    with pytest.raises(RuntimeError, match="fee is NOT_OBSERVED"):
        execute_paper_against_route_book(
            route=_route(), book=_book(), providers=_providers(None),
            side="BUY", quantity=1.0, policy=POLICY,
        )


def test_missing_displayed_size_rejects_instead_of_inventing_depth() -> None:
    fact = execute_paper_against_route_book(
        route=_route(), book=_book(ask_size=None), providers=_providers(),
        side="BUY", quantity=1.0, policy=POLICY,
    )
    assert fact.fill.accepted is False
    assert fact.fill.average_price is None
    assert fact.fill.rejection_reason == "EXECUTABLE_DEPTH_NOT_OBSERVED"


def test_non_executable_book_cannot_fill_even_if_other_prices_exist_elsewhere() -> None:
    with pytest.raises(RuntimeError, match="requires EXECUTABLE"):
        execute_paper_against_route_book(
            route=_route(),
            book=_book(ExecutionState.NOT_OBSERVED),
            providers=_providers(),
            side="BUY",
            quantity=1.0,
            policy=POLICY,
        )
