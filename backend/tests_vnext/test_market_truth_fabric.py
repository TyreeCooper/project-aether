from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aether_vnext.market_truth_contract import ExecutionState, ProviderRole
from aether_vnext.market_truth_fabric import (
    ParsedExecutablePacket,
    apply_executable_packet,
    executable_transport_down,
    refresh_executable_state,
)
from aether_vnext.market_truth_provider import ProviderCard, ProviderCardRegistry, ProviderFeeSchedule
from aether_vnext.market_truth_route import RouteRecord


NOW = datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc)


def _providers() -> ProviderCardRegistry:
    return ProviderCardRegistry((
        ProviderCard(
            "kraken", ProviderRole.BOTH, "Kraken",
            ProviderFeeSchedule("kraken-reviewed"),
            "public_market_data;paper_execution_only;live_not_authorized",
        ),
    ))


def _route() -> RouteRecord:
    return RouteRecord(
        canonical_instrument_id="btc-usd",
        executable_provider_id="kraken",
        witness_provider_ids=(),
        human_set_by="operator",
        human_set_at_utc=NOW,
        route_revision=1,
    )


def _packet(**updates) -> ParsedExecutablePacket:
    values = dict(
        canonical_instrument_id="btc-usd",
        provider_id="kraken",
        venue="Kraken",
        transport_id="kraken-ws-v2-primary",
        bid=65000.0,
        ask=65001.0,
        last_if_printed=None,
        bid_size=1.25,
        ask_size=0.75,
        venue_time_utc=NOW,
        receive_time_utc=NOW,
    )
    values.update(updates)
    return ParsedExecutablePacket(**values)


def test_fresh_provider_book_is_published_without_calculation() -> None:
    snapshot = apply_executable_packet(
        _route(), _packet(), providers=_providers(), as_of_utc=NOW, stale_after_ms=2000
    )
    assert snapshot.state is ExecutionState.EXECUTABLE
    assert snapshot.bid == 65000.0
    assert snapshot.ask == 65001.0
    assert snapshot.last_if_printed is None
    assert snapshot.bid_size == 1.25
    assert snapshot.ask_size == 0.75
    assert "mid" not in snapshot.__dataclass_fields__
    assert "mark" not in snapshot.__dataclass_fields__


def test_missing_provider_field_is_null_and_missing_side_blanks_execution_price() -> None:
    snapshot = apply_executable_packet(
        _route(), _packet(bid=None), providers=_providers(), as_of_utc=NOW, stale_after_ms=2000
    )
    assert snapshot.state is ExecutionState.NOT_OBSERVED
    assert snapshot.bid is None
    assert snapshot.ask is None
    assert snapshot.last_if_printed is None


def test_stale_book_blanks_all_market_values() -> None:
    snapshot = apply_executable_packet(
        _route(),
        _packet(receive_time_utc=NOW - timedelta(seconds=3)),
        providers=_providers(),
        as_of_utc=NOW,
        stale_after_ms=2000,
    )
    assert snapshot.state is ExecutionState.STALE
    assert snapshot.bid is None and snapshot.ask is None
    assert snapshot.last_if_printed is None
    assert snapshot.bid_size is None and snapshot.ask_size is None


def test_live_snapshot_ages_to_stale_without_carry_forward() -> None:
    live = apply_executable_packet(
        _route(), _packet(), providers=_providers(), as_of_utc=NOW, stale_after_ms=2000
    )
    stale = refresh_executable_state(
        live, as_of_utc=NOW + timedelta(seconds=3), stale_after_ms=2000
    )
    assert stale.state is ExecutionState.STALE
    assert stale.bid is None and stale.ask is None


def test_cable_pull_blanks_price_even_without_witness_logic() -> None:
    down = executable_transport_down(_route(), providers=_providers())
    assert down.state is ExecutionState.NOT_OBSERVED
    assert down.bid is None
    assert down.ask is None
    assert down.last_if_printed is None
