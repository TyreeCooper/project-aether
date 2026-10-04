from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.market_truth_contract import ProviderRole
from aether_vnext.market_truth_provider import ProviderCard, ProviderCardRegistry, ProviderFeeSchedule
from aether_vnext.market_truth_route import HumanRouteRegistry, RouteRecord, same_route_transport_failover
from aether_vnext.market_truth_universe import AssetUniverse, AssetUniverseRow


NOW = datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc)


def _universe() -> AssetUniverse:
    return AssetUniverse((
        AssetUniverseRow("btc-usd", "spot_crypto", 0.1, 0.0001, "crypto_24x7"),
        AssetUniverseRow("eth-usd", "spot_crypto", 0.01, 0.001, "crypto_24x7"),
    ))


def _providers() -> ProviderCardRegistry:
    return ProviderCardRegistry((
        ProviderCard(
            "kraken", ProviderRole.BOTH, "Kraken",
            ProviderFeeSchedule("kraken-reviewed"),
            "public_book;paper_execution_only;live_not_authorized",
        ),
        ProviderCard(
            "coinbase-witness", ProviderRole.OBSERVE, "Coinbase",
            ProviderFeeSchedule("no_execution_fee"),
            "public_market_data_only",
        ),
    ))


def _route(instrument: str = "btc-usd", revision: int = 1) -> RouteRecord:
    return RouteRecord(
        canonical_instrument_id=instrument,
        executable_provider_id="kraken",
        witness_provider_ids=("coinbase-witness",),
        human_set_by="operator",
        human_set_at_utc=NOW,
        route_revision=revision,
    )


def test_route_is_human_attributed_and_transport_free() -> None:
    route = _route()
    assert route.human_set_by == "operator"
    assert "transport" not in route.__dataclass_fields__
    assert route.route_id.startswith("route:btc-usd:")


def test_first_proof_gate_blocks_second_executable_route() -> None:
    registry = HumanRouteRegistry(universe=_universe(), providers=_providers())
    registry.add_human_route(_route("btc-usd"))
    with pytest.raises(RuntimeError, match="second executable route"):
        registry.add_human_route(_route("eth-usd"))


def test_second_route_allowed_only_after_proof_evidence_is_bound() -> None:
    registry = HumanRouteRegistry(universe=_universe(), providers=_providers())
    registry.add_human_route(_route("btc-usd"))
    registry.mark_first_proof_passed(proof_evidence_id="proof:btc-usd:001")
    registry.add_human_route(_route("eth-usd"))
    assert len(registry.routes()) == 2


def test_automatic_execution_route_change_has_no_api() -> None:
    registry = HumanRouteRegistry(universe=_universe(), providers=_providers(), routes=(_route(),))
    assert not hasattr(registry, "automatic_switch")
    replacement = registry.replace_human_route(
        "btc-usd",
        executable_provider_id="kraken",
        witness_provider_ids=(),
        human_set_by="operator-2",
        human_set_at_utc=NOW,
    )
    assert replacement.route_revision == 2
    assert replacement.human_set_by == "operator-2"


def test_transport_failover_is_not_route_change_only_for_same_provider_and_venue() -> None:
    route = _route()
    providers = _providers()
    assert same_route_transport_failover(
        route, provider_id="kraken", venue="Kraken", providers=providers
    ) is True
    assert same_route_transport_failover(
        route, provider_id="kraken", venue="OtherVenue", providers=providers
    ) is False
