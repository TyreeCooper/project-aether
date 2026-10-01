from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.runtime_product_policy import (
    paper_broker_account_for_product,
    resolve_runtime_product,
    runtime_cluster_for_product,
    runtime_cluster_map,
)
from aether_vnext.store import VNextStore
from tests_vnext.runtime_registry_support import record_test_runtime_binding


UTC = timezone.utc
T0 = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=CONFIGURATION_HASH,
                policy_version="runtime-product-policy-test",
                effective_at_utc=T0 - timedelta(days=1),
                changed_by="test",
                change_reason="runtime product policy",
                payload={},
                created_at_utc=T0 - timedelta(days=1),
            )
        )
    return engine, store


def _dynamic_sol():
    projection = project_kraken_spot_product(
        {
            "provider": "Kraken",
            "symbol": "SOL/USD",
            "execution_symbol": "SOLUSD",
            "asset_class": "spot_crypto",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "quantity_step": 0.001,
            "minimum_quantity": 0.02,
            "minimum_notional": 0.5,
            "tick_size": 0.0001,
        },
        primary_market_source_id="kraken_public",
        stale_threshold_ms=15_000,
    )
    assert projection.product is not None
    return projection


def test_seed_product_keeps_existing_cluster_and_paper_sleeve() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        record_test_runtime_binding(
            conn,
            store,
            asset_id="btc",
            configuration_hash=CONFIGURATION_HASH,
            now=T0,
        )
        resolved = resolve_runtime_product(
            conn,
            store,
            asset_id="btc",
            as_of_utc=T0,
        )

    assert resolved.source_kind == "runtime_binding"
    assert resolved.product.asset_id == "btc"
    assert runtime_cluster_for_product(resolved.product) == "crypto"
    assert paper_broker_account_for_product(resolved.product) == "kraken_paper"


def test_dynamic_kraken_spot_uses_same_crypto_risk_cluster_and_paper_sleeve() -> None:
    engine, store = _store()
    projection = _dynamic_sol()
    with engine.begin() as conn:
        digest = store.upsert_dynamic_product_state(
            conn,
            projection.product,
            source_ref="kraken:AssetPairs:SOLUSD",
            registry_version="dynamic-kraken-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        resolved = resolve_runtime_product(
            conn,
            store,
            asset_id=projection.asset_id,
            as_of_utc=T0,
        )

    assert resolved.source_kind == "dynamic_product"
    assert resolved.identity_hash == digest
    assert resolved.configuration_hash == CONFIGURATION_HASH
    assert runtime_cluster_for_product(resolved.product) == "crypto"
    assert paper_broker_account_for_product(resolved.product) == "kraken_paper"
    clusters = runtime_cluster_map((resolved.product,))
    assert clusters["btc"] == "crypto"
    assert clusters["eth"] == "crypto"
    assert clusters["kraken:solusd"] == "crypto"


def test_unknown_product_has_no_fabricated_runtime_policy() -> None:
    projection = _dynamic_sol()
    product = projection.product
    assert product is not None

    from dataclasses import replace
    from aether_vnext.registry import ProductType

    unsupported = replace(
        product,
        asset_id="dynamic:unknown",
        product_type=ProductType.EQUITY,
        broker="unknown-broker",
        venue="unknown-venue",
    )

    try:
        runtime_cluster_for_product(unsupported)
    except RuntimeError as exc:
        assert "dynamic risk cluster not bound" in str(exc)
    else:
        raise AssertionError("unsupported dynamic product must not get a cluster")

    try:
        paper_broker_account_for_product(unsupported)
    except RuntimeError as exc:
        assert "paper broker account not bound" in str(exc)
    else:
        raise AssertionError("unsupported broker must not get a paper sleeve")
