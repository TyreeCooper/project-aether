from __future__ import annotations

import pytest

from aether_vnext.market_truth_contract import ProviderRole
from aether_vnext.market_truth_provider import (
    ProviderCard,
    ProviderCardRegistry,
    ProviderFeeSchedule,
)
from aether_vnext.market_truth_universe import AssetUniverse, AssetUniverseRow


def test_asset_universe_row_contains_identity_only() -> None:
    row = AssetUniverseRow(
        canonical_instrument_id="btc-usd",
        asset_class="spot_crypto",
        tick_size=0.1,
        lot_size=0.0001,
        session_calendar="crypto_24x7",
    )
    assert tuple(row.__dataclass_fields__) == (
        "canonical_instrument_id",
        "asset_class",
        "tick_size",
        "lot_size",
        "session_calendar",
    )
    forbidden = {
        "bid", "ask", "last", "price", "provider_id", "venue",
        "fee_schedule", "route_id", "adapter_id",
    }
    assert forbidden.isdisjoint(row.__dataclass_fields__)


def test_asset_universe_rejects_missing_market_structure_facts() -> None:
    with pytest.raises(ValueError, match="tick_size"):
        AssetUniverseRow(
            canonical_instrument_id="btc-usd",
            asset_class="spot_crypto",
            tick_size=0.0,
            lot_size=0.0001,
            session_calendar="crypto_24x7",
        )
    universe = AssetUniverse((
        AssetUniverseRow("btc-usd", "spot_crypto", 0.1, 0.0001, "crypto_24x7"),
    ))
    assert universe.ids() == ("btc-usd",)


def test_provider_card_owns_capability_entitlement_and_fee_schedule() -> None:
    schedule = ProviderFeeSchedule(schedule_id="kraken_spot_reviewed")
    card = ProviderCard(
        provider_id="kraken",
        role=ProviderRole.BOTH,
        venue="Kraken",
        fee_schedule=schedule,
        entitlement="public_market_data;paper_execution_only;live_not_authorized",
    )
    registry = ProviderCardRegistry((card,))
    assert registry.require("kraken").can_observe is True
    assert registry.require("kraken").can_execute is True
    assert registry.require("kraken").fee_schedule is schedule


def test_observe_only_provider_cannot_execute() -> None:
    card = ProviderCard(
        provider_id="witness",
        role=ProviderRole.OBSERVE,
        venue="WitnessVenue",
        fee_schedule=ProviderFeeSchedule(schedule_id="no_execution_fees"),
        entitlement="public_market_data_only",
    )
    assert card.can_observe is True
    assert card.can_execute is False
