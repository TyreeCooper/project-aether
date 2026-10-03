from __future__ import annotations

import pytest

from aether_vnext.registry import ProductType
from aether_vnext.tape_policy import (
    TAPE_POLICY_TEMPLATES,
    TapeAssetClass,
    TapeQuorumPolicy,
    tape_asset_class,
    tape_policy_template_for_product_type,
)


def test_all_tape_asset_classes_require_three_sources_and_support_five() -> None:
    assert set(TAPE_POLICY_TEMPLATES) == set(TapeAssetClass)
    for policy in TAPE_POLICY_TEMPLATES.values():
        assert policy.required_quorum == 3
        assert policy.degraded_quorum == 2
        assert policy.max_sources == 5
        assert policy.require_independent_sources is True


def test_unbound_numeric_policy_is_explicitly_nonoperational() -> None:
    policy = tape_policy_template_for_product_type(ProductType.SPOT_CRYPTO)
    assert policy.operational is False
    assert policy.missing_requirements == (
        "tape_source_freshness_policy_unbound",
        "tape_divergence_policy_unbound",
    )


def test_asset_class_mapping_keeps_futures_together_without_merging_economics() -> None:
    assert tape_asset_class(ProductType.SPOT_CRYPTO) is TapeAssetClass.CRYPTO
    assert tape_asset_class(ProductType.MICRO_FUTURE) is TapeAssetClass.FUTURES
    assert tape_asset_class(ProductType.TREASURY_FUTURE) is TapeAssetClass.FUTURES
    assert tape_asset_class(ProductType.FX) is TapeAssetClass.FX
    assert tape_asset_class(ProductType.EQUITY) is TapeAssetClass.EQUITIES


def test_bound_policy_validates_quorum_and_thresholds() -> None:
    policy = TapeQuorumPolicy(
        asset_class=TapeAssetClass.FUTURES,
        required_quorum=3,
        degraded_quorum=2,
        max_sources=5,
        max_source_age_ms=1000,
        max_divergence_bps=5.0,
    )
    assert policy.operational is True
    assert policy.missing_requirements == ()

    with pytest.raises(ValueError, match="fewer than three"):
        TapeQuorumPolicy(
            asset_class=TapeAssetClass.FUTURES,
            required_quorum=2,
        )
