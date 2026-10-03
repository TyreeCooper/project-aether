from __future__ import annotations

import pytest

from aether_vnext.playbooks import (
    PLAYBOOK_ASSET_RISK_HITCHES,
    PLAYBOOK_REGISTRY,
    SEED_ASSET_CLUSTERS,
    asset_risk_hitches,
    cluster_for_asset,
    cluster_for_playbook,
)


EXPECTED_CLUSTERS = {
    "btc": "crypto",
    "eth": "crypto",
    "eurusd": "fx",
    "usdjpy": "fx",
    "mes": "us_beta",
    "mnq": "us_beta",
    "mgc": "metal",
    "mcl": "energy",
    "us10y": "rates",
    "nvda": "us_beta",
    "tsla": "us_beta",
    "pltr": "us_beta",
}


def test_seed_twelve_cluster_map_is_exact_and_complete() -> None:
    assert dict(SEED_ASSET_CLUSTERS) == EXPECTED_CLUSTERS
    assert len(SEED_ASSET_CLUSTERS) == 12


def test_every_bound_playbook_stays_inside_one_canonical_risk_cluster() -> None:
    for playbook_id, spec in PLAYBOOK_REGISTRY.items():
        clusters = {
            cluster_for_asset(asset_id)
            for asset_id in spec.allowed_assets
        }
        assert len(clusters) == 1
        assert cluster_for_playbook(playbook_id) == next(iter(clusters))


def test_us_beta_is_shared_by_index_futures_and_equities() -> None:
    for asset_id in ("mes", "mnq", "nvda", "tsla", "pltr"):
        assert cluster_for_asset(asset_id) == "us_beta"


def test_metal_energy_and_rates_remain_separate_clusters() -> None:
    assert cluster_for_asset("mgc") == "metal"
    assert cluster_for_asset("mcl") == "energy"
    assert cluster_for_asset("us10y") == "rates"


def test_eth_rider_hitches_are_exact_and_do_not_net_risk() -> None:
    assert set(PLAYBOOK_ASSET_RISK_HITCHES) == {
        "pb_eth_rider_v1_2",
        "pb_eth_failed_break_v1_3",
    }
    assert dict(asset_risk_hitches("pb_eth_rider_v1_2")) == {
        "btc": 0.50
    }
    assert dict(asset_risk_hitches("pb_eth_failed_break_v1_3")) == {
        "btc": 0.50
    }
    assert dict(asset_risk_hitches("pb_crypto_swing_v1_2")) == {}


def test_unknown_asset_cluster_fails_closed() -> None:
    with pytest.raises(KeyError, match="canonical cluster"):
        cluster_for_asset("unknown")


def test_unknown_playbook_hitch_lookup_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown playbook_id"):
        asset_risk_hitches("pb_not_real")
