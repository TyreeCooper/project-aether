"""Runtime product policy for seed and source-backed dynamic assets.

This layer extends existing Firm routing laws to verified runtime products without
mutating frozen seed truth. It does not create provider facts, relax Risk limits, or
authorize LIVE execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Iterable

from sqlalchemy.engine import Connection

from aether_vnext.playbooks import SEED_ASSET_CLUSTERS, cluster_for_asset
from aether_vnext.registry import ProductRegistryRow, ProductType, SEED_REGISTRY
from aether_vnext.registry_runtime import materialize_bound_registry_row
from aether_vnext.seed_truth import BROKER_ACCOUNT_BY_BROKER

if TYPE_CHECKING:
    from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class RuntimeProductResolution:
    product: ProductRegistryRow
    identity_hash: str
    configuration_hash: str
    source_kind: str


def resolve_runtime_product(
    conn: Connection,
    store: "VNextStore",
    *,
    asset_id: str,
    as_of_utc: datetime,
) -> RuntimeProductResolution:
    """Resolve reviewed seed binding or hash-verified dynamic product state."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    aid = str(asset_id).strip().lower()
    if not aid:
        raise ValueError("asset_id is required")

    runtime = store.load_runtime_registry_binding(conn, asset_id=aid)
    if runtime is not None:
        product = materialize_bound_registry_row(
            runtime["binding"],
            as_of_utc=as_of_utc,
        )
        if product.asset_id != aid:
            raise RuntimeError("runtime product asset mismatch")
        return RuntimeProductResolution(
            product=product,
            identity_hash=str(runtime["binding_hash"]),
            configuration_hash=str(runtime["configuration_hash"]),
            source_kind="runtime_binding",
        )

    dynamic = store.load_dynamic_product_state(conn, asset_id=aid)
    if dynamic is not None:
        product = dynamic["product"]
        if product.asset_id != aid:
            raise RuntimeError("dynamic product asset mismatch")
        return RuntimeProductResolution(
            product=product,
            identity_hash=str(dynamic["product_hash"]),
            configuration_hash=str(dynamic["configuration_hash"]),
            source_kind="dynamic_product",
        )

    raise RuntimeError(f"runtime product binding missing: {aid}")


def runtime_cluster_for_product(product: ProductRegistryRow) -> str:
    """Resolve the existing Firm risk cluster without inventing a new cluster."""
    asset_id = str(product.asset_id).strip().lower()
    if asset_id in SEED_REGISTRY:
        return cluster_for_asset(asset_id)

    # Dynamic Kraken spot products share the same existing crypto risk envelope as
    # BTC/ETH. This preserves the asset/cluster/portfolio caps instead of creating
    # a separate capacity bucket for newly discovered crypto.
    if (
        product.product_type is ProductType.SPOT_CRYPTO
        and product.broker == "Kraken"
        and product.venue == "Kraken"
    ):
        return "crypto"

    raise RuntimeError(
        f"dynamic risk cluster not bound for product: {asset_id}"
    )


def paper_broker_account_for_product(product: ProductRegistryRow) -> str:
    """Route through an already provisioned PAPER sleeve for the product broker."""
    account = BROKER_ACCOUNT_BY_BROKER.get(str(product.broker))
    if account is None:
        raise RuntimeError(
            f"paper broker account not bound for broker: {product.broker}"
        )
    return str(account)


def runtime_cluster_map(
    dynamic_products: Iterable[ProductRegistryRow] = (),
) -> dict[str, str]:
    """Return seed cluster truth plus verified dynamic product assignments."""
    mapping = dict(SEED_ASSET_CLUSTERS)
    for product in dynamic_products:
        asset_id = str(product.asset_id).strip().lower()
        if asset_id in mapping:
            if mapping[asset_id] != runtime_cluster_for_product(product):
                raise RuntimeError(
                    f"runtime cluster drift for seed asset: {asset_id}"
                )
            continue
        mapping[asset_id] = runtime_cluster_for_product(product)
    return mapping
