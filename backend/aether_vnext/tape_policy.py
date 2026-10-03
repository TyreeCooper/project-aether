"""Policy contract for AETHER Consensus Tape quorum and source quality.

The operator has authorized a three-source minimum and five-source capacity. Numeric
freshness and cross-source divergence tolerances remain asset-class policy facts and
must be explicitly bound; this module does not invent them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from aether_vnext.registry import ProductType
from aether_vnext.tape import MAX_TAPE_SOURCES


class TapeAssetClass(StrEnum):
    CRYPTO = "crypto"
    FUTURES = "futures"
    FX = "fx"
    EQUITIES = "equities"


@dataclass(frozen=True, slots=True)
class TapeQuorumPolicy:
    asset_class: TapeAssetClass
    required_quorum: int = 3
    degraded_quorum: int = 2
    max_sources: int = MAX_TAPE_SOURCES
    max_source_age_ms: int | None = None
    max_divergence_bps: float | None = None
    require_independent_sources: bool = True

    def __post_init__(self) -> None:
        if self.required_quorum < 3:
            raise ValueError("full Tape quorum cannot be fewer than three sources")
        if self.max_sources < self.required_quorum:
            raise ValueError("max_sources cannot be below full quorum")
        if self.max_sources > MAX_TAPE_SOURCES:
            raise ValueError("max_sources exceeds Tape capacity")
        if self.degraded_quorum < 1 or self.degraded_quorum >= self.required_quorum:
            raise ValueError("degraded_quorum must be below full quorum")
        if self.max_source_age_ms is not None and self.max_source_age_ms <= 0:
            raise ValueError("max_source_age_ms must be positive when bound")
        if self.max_divergence_bps is not None and self.max_divergence_bps <= 0:
            raise ValueError("max_divergence_bps must be positive when bound")

    @property
    def operational(self) -> bool:
        return (
            self.max_source_age_ms is not None
            and self.max_divergence_bps is not None
        )

    @property
    def missing_requirements(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.max_source_age_ms is None:
            missing.append("tape_source_freshness_policy_unbound")
        if self.max_divergence_bps is None:
            missing.append("tape_divergence_policy_unbound")
        return tuple(missing)


TAPE_POLICY_TEMPLATES: Final = MappingProxyType(
    {
        asset_class: TapeQuorumPolicy(asset_class=asset_class)
        for asset_class in TapeAssetClass
    }
)


def tape_asset_class(product_type: ProductType) -> TapeAssetClass:
    if product_type is ProductType.SPOT_CRYPTO:
        return TapeAssetClass.CRYPTO
    if product_type in {
        ProductType.MICRO_FUTURE,
        ProductType.TREASURY_FUTURE,
    }:
        return TapeAssetClass.FUTURES
    if product_type is ProductType.FX:
        return TapeAssetClass.FX
    if product_type is ProductType.EQUITY:
        return TapeAssetClass.EQUITIES
    raise ValueError(f"unsupported Tape product type: {product_type}")


def tape_policy_template_for_product_type(
    product_type: ProductType,
) -> TapeQuorumPolicy:
    return TAPE_POLICY_TEMPLATES[tape_asset_class(product_type)]
