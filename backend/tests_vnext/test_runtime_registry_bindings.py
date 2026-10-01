from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.forward_paper_preflight import (
    ForwardPaperRouteRequest,
    preflight_forward_paper_campaign_from_book,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.ibkr_webapi_market import (
    IBKR_WEBAPI_MARKET_SOURCE_ID,
    IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
)
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID
from aether_vnext.registry_runtime import (
    RuntimeRegistryBinding,
    binding_blockers,
    binding_hash,
    materialize_bound_registry_row,
)
from aether_vnext.store import VNextStore
from tests_vnext.held_out_support import record_provenanced_held_out
from tests_vnext.runtime_registry_support import make_runtime_binding


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 1, 15, tzinfo=UTC)


def _store(config: str = CONFIGURATION_HASH) -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash=config,
                policy_version="runtime-binding-policy",
                effective_at_utc=T0 - timedelta(days=30),
                changed_by="test",
                change_reason="runtime binding",
                payload={},
                created_at_utc=T0 - timedelta(days=30),
            )
        )
    return engine, store


def test_runtime_binding_round_trip_is_hash_verified() -> None:
    engine, store = _store()
    binding = make_runtime_binding("eurusd", now=T0)

    with engine.begin() as conn:
        digest = store.upsert_runtime_registry_binding(
            conn,
            binding,
            registry_version="registry-runtime-test-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        loaded = store.load_runtime_registry_binding(
            conn,
            asset_id="eurusd",
        )

    assert loaded is not None
    assert loaded["binding"] == binding
    assert loaded["binding_hash"] == digest == binding_hash(binding)
    assert loaded["configuration_hash"] == CONFIGURATION_HASH


def test_incomplete_binding_persists_but_remains_fail_closed() -> None:
    engine, store = _store()
    binding = RuntimeRegistryBinding(
        asset_id="btc",
        broker_symbol="XBTUSD",
        primary_market_source_id="kraken_public",
        stale_threshold_ms=None,
        calendar_provider_id=None,
        source_ref="test-incomplete",
    )
    assert binding_blockers(binding) == ("stale_threshold_missing",)

    with engine.begin() as conn:
        store.upsert_runtime_registry_binding(
            conn,
            binding,
            registry_version="registry-runtime-test-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        loaded = store.load_runtime_registry_binding(conn, asset_id="btc")

    assert loaded is not None
    assert loaded["binding"] == binding


def test_complete_binding_materializes_market_ready_product_truth() -> None:
    binding = make_runtime_binding("eurusd", now=T0)
    row = materialize_bound_registry_row(binding, as_of_utc=T0)

    assert row.asset_id == "eurusd"
    assert row.market_data_ready() is True
    assert row.broker_symbol == "EUR/USD"
    assert row.primary_market_source_id == "test.market.eurusd"
    assert row.stale_threshold_ms == 1500


def test_futures_binding_refuses_contract_inside_roll_cutoff() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="mes",
        broker_symbol="MESTEST1",
        primary_market_source_id="test.market.mes",
        stale_threshold_ms=1500,
        calendar_provider_id="test.calendar",
        current_contract="MESTEST1",
        expiry_utc=T0 + timedelta(hours=47),
        next_contract="MESTEST2",
        source_ref="test-roll",
    )
    assert "futures_contract_in_roll_cutoff" in binding_blockers(
        binding,
        as_of_utc=T0,
    )


def test_forward_preflight_rejects_unbound_runtime_product_even_with_real_heldout_chain() -> None:
    engine, store = _store()
    window = EvidenceWindow(
        evidence_window_id="heldout-runtime-gate",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="runtime-binding-policy",
        configuration_hash=CONFIGURATION_HASH,
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=T0 - timedelta(days=10),
        last_timestamp_utc=T0 - timedelta(days=9),
        n=1,
        immutable_trade_ids=("hist-runtime-1",),
        metrics_snapshot_hash="metrics-runtime-1",
        created_at_utc=T0 - timedelta(days=1),
    )

    with engine.begin() as conn:
        record_provenanced_held_out(conn, store, window)
        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="runtime-binding-gate",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
            as_of_utc=T0,
        )

    assert out.startable is False
    assert out.route_results[0].held_out_window_count == 1
    assert "runtime_product_binding_missing" in out.route_results[0].blockers


def test_strict_preflight_rejects_bound_source_without_repository_adapter() -> None:
    engine, store = _store()
    binding = make_runtime_binding("eurusd", now=T0)
    window = EvidenceWindow(
        evidence_window_id="heldout-source-implementation-gate",
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="runtime-binding-policy",
        configuration_hash=CONFIGURATION_HASH,
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=T0 - timedelta(days=10),
        last_timestamp_utc=T0 - timedelta(days=9),
        n=1,
        immutable_trade_ids=("hist-source-1",),
        metrics_snapshot_hash="metrics-source-implementation-1",
        created_at_utc=T0 - timedelta(days=1),
    )

    with engine.begin() as conn:
        store.upsert_runtime_registry_binding(
            conn,
            binding,
            registry_version="registry-runtime-test-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        record_provenanced_held_out(conn, store, window)
        out = preflight_forward_paper_campaign_from_book(
            conn,
            store,
            campaign_id="source-implementation-gate",
            requested_routes=(
                ForwardPaperRouteRequest(
                    route_id="eurusd:intraday:long",
                    playbook_id="pb_fx_intraday_v1_2",
                ),
            ),
            as_of_utc=T0,
            require_market_source_implementation=True,
        )

    assert out.startable is False
    assert out.route_results[0].held_out_window_count == 1
    assert (
        "primary_market_source_implementation_missing"
        in out.route_results[0].blockers
    )


def test_ninjatrader_futures_binding_requires_reviewed_contract_id() -> None:
    missing = RuntimeRegistryBinding(
        asset_id="mes",
        broker_symbol="MESZ6",
        primary_market_source_id=NINJATRADER_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="reviewed.calendar",
        current_contract="MESZ6",
        market_data_contract_id=None,
        expiry_utc=T0 + timedelta(days=60),
        next_contract="MESH7",
        source_ref="reviewed-ninjatrader-binding",
    )
    blockers = binding_blockers(missing, as_of_utc=T0)
    assert "market_data_contract_id_missing" in blockers

    bound = RuntimeRegistryBinding(
        asset_id="mes",
        broker_symbol="MESZ6",
        primary_market_source_id=NINJATRADER_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="reviewed.calendar",
        current_contract="MESZ6",
        market_data_contract_id=987654,
        expiry_utc=T0 + timedelta(days=60),
        next_contract="MESH7",
        source_ref="reviewed-ninjatrader-binding",
    )
    assert "market_data_contract_id_missing" not in binding_blockers(
        bound,
        as_of_utc=T0,
    )
    assert binding_hash(bound) != binding_hash(missing)


def test_market_data_contract_id_must_be_positive_integer() -> None:
    with pytest.raises(ValueError, match="market_data_contract_id"):
        RuntimeRegistryBinding(
            asset_id="mes",
            broker_symbol="MESZ6",
            primary_market_source_id=NINJATRADER_MARKET_SOURCE_ID,
            stale_threshold_ms=1500,
            calendar_provider_id="reviewed.calendar",
            current_contract="MESZ6",
            market_data_contract_id=0,
            expiry_utc=T0 + timedelta(days=60),
            next_contract="MESH7",
        )


def test_non_futures_binding_rejects_market_data_contract_id() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="btc",
        broker_symbol="XBTUSD",
        primary_market_source_id="kraken_public",
        stale_threshold_ms=1000,
        calendar_provider_id=None,
        market_data_contract_id=123,
    )
    assert "non_futures_contract_fields_present" in binding_blockers(binding)


def test_fx_otc_strict_calendar_gate_uses_frozen_weekly_contract() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="eurusd",
        broker_symbol="EUR/USD",
        primary_market_source_id="reviewed.fx.source",
        stale_threshold_ms=1500,
        calendar_provider_id=None,
        source_ref="reviewed-fx-binding",
    )
    blockers = binding_blockers(
        binding,
        as_of_utc=T0,
        require_calendar_provider_implementation=True,
    )
    assert "calendar_provider_missing" not in blockers
    assert "calendar_provider_implementation_missing" not in blockers
    assert "calendar_provider_calendar_unsupported" not in blockers


def test_ibkr_equity_binding_requires_reviewed_conid() -> None:
    missing = RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=None,
        shortability_provider_id="reviewed.locate",
        shortability_stale_threshold_ms=1500,
        source_ref="reviewed-ibkr-binding",
    )
    blockers = binding_blockers(missing)
    assert "market_data_contract_id_missing" in blockers

    bound = RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=4815747,
        shortability_provider_id="reviewed.locate",
        shortability_stale_threshold_ms=1500,
        source_ref="reviewed-ibkr-binding",
    )
    assert "market_data_contract_id_missing" not in binding_blockers(bound)
    assert "non_futures_contract_fields_present" not in binding_blockers(bound)
    assert binding_hash(bound) != binding_hash(missing)


def test_ibkr_equity_strict_source_gate_accepts_implemented_transport() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="tsla",
        broker_symbol="TSLA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=76792991,
        shortability_provider_id="reviewed.locate",
        shortability_stale_threshold_ms=1500,
        source_ref="reviewed-ibkr-binding",
    )
    blockers = binding_blockers(
        binding,
        require_market_source_implementation=True,
    )
    assert "primary_market_source_implementation_missing" not in blockers
    assert "primary_market_source_asset_unsupported" not in blockers


def test_ibkr_shortability_strict_provider_gate_requires_implemented_source() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=4815747,
        shortability_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        shortability_stale_threshold_ms=1500,
        source_ref="reviewed-ibkr-binding",
    )
    blockers = binding_blockers(
        binding,
        require_shortability_provider_implementation=True,
    )
    assert "shortability_provider_implementation_missing" not in blockers
    assert "shortability_provider_asset_unsupported" not in blockers
    assert "shortability_stale_threshold_missing" not in blockers

    unknown = RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=4815747,
        shortability_provider_id="reviewed.locate",
        shortability_stale_threshold_ms=1500,
        source_ref="reviewed-ibkr-binding",
    )
    assert "shortability_provider_implementation_missing" in binding_blockers(
        unknown,
        require_shortability_provider_implementation=True,
    )


def test_strict_market_print_gate_accepts_implemented_crypto_and_equity_sources() -> None:
    crypto = RuntimeRegistryBinding(
        asset_id="btc",
        broker_symbol="XBTUSD",
        primary_market_source_id="kraken_public",
        stale_threshold_ms=1500,
        calendar_provider_id=None,
        source_ref="reviewed-kraken-binding",
    )
    assert "market_print_source_implementation_missing" not in binding_blockers(
        crypto,
        require_market_print_implementation=True,
    )

    equity = RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=4815747,
        shortability_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        shortability_stale_threshold_ms=1500,
        source_ref="reviewed-ibkr-binding",
    )
    assert "market_print_source_implementation_missing" not in binding_blockers(
        equity,
        require_market_print_implementation=True,
    )



def test_dynamic_product_state_round_trip_does_not_replace_seed_registry() -> None:
    engine, store = _store()
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

    with engine.begin() as conn:
        digest = store.upsert_dynamic_product_state(
            conn,
            projection.product,
            source_ref="kraken:AssetPairs:SOLUSD",
            registry_version="dynamic-kraken-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=T0,
        )
        loaded = store.load_dynamic_product_state(
            conn,
            asset_id=projection.asset_id,
        )
        runtime_binding = store.load_runtime_registry_binding(
            conn,
            asset_id=projection.asset_id,
        )

    assert loaded is not None
    assert loaded["product"] == projection.product
    assert loaded["product_hash"] == digest
    assert runtime_binding is None
