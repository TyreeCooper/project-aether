from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.ibkr_webapi_market import (
    IBKR_WEBAPI_MARKET_SOURCE_ID,
    IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
)
from aether_vnext.playbooks import cluster_for_asset
from aether_vnext.registry_runtime import (
    RuntimeRegistryBinding,
    binding_blockers,
    materialize_bound_registry_row,
)
from aether_vnext.shortability import (
    build_shortability_evidence,
    evaluate_shortability,
)
from aether_vnext.store import VNextStore, open_intent_idempotency_key


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
CONID = 4815747


def _evidence(
    *,
    shares: float = 1000,
    updated_at: datetime = T0,
    availability: str = "RpB",
):
    return build_shortability_evidence(
        asset_id="nvda",
        provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        market_data_contract_id=CONID,
        shortable_shares=shares,
        fee_rate_raw="0.42",
        shortable_raw="Shortable",
        market_data_availability=availability,
        provider_updated_at_utc=updated_at,
        received_at_utc=updated_at,
        adapter_version="test-shortability-v1",
    )


def test_shortability_decision_requires_fresh_realtime_sufficient_shares() -> None:
    allowed = evaluate_shortability(
        _evidence(shares=100),
        expected_asset_id="nvda",
        expected_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        expected_contract_id=CONID,
        requested_shares=10,
        as_of_utc=T0 + timedelta(milliseconds=500),
        max_age_ms=1500,
    )
    assert allowed.allowed is True
    assert allowed.reason == "shortability_available"
    assert allowed.available_shares == 100

    insufficient = evaluate_shortability(
        _evidence(shares=5),
        expected_asset_id="nvda",
        expected_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        expected_contract_id=CONID,
        requested_shares=10,
        as_of_utc=T0 + timedelta(milliseconds=500),
        max_age_ms=1500,
    )
    assert insufficient.allowed is False
    assert insufficient.reason == "shortability_insufficient_shares"

    stale = evaluate_shortability(
        _evidence(shares=100),
        expected_asset_id="nvda",
        expected_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        expected_contract_id=CONID,
        requested_shares=10,
        as_of_utc=T0 + timedelta(seconds=2),
        max_age_ms=1500,
    )
    assert stale.allowed is False
    assert stale.reason == "shortability_evidence_stale"

    delayed = evaluate_shortability(
        _evidence(shares=100, availability="DpB"),
        expected_asset_id="nvda",
        expected_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        expected_contract_id=CONID,
        requested_shares=10,
        as_of_utc=T0 + timedelta(milliseconds=100),
        max_age_ms=1500,
    )
    assert delayed.allowed is False
    assert delayed.reason == "shortability_not_realtime"


def _observation() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-nvda",
        asset_id="nvda",
        venue="IBKR",
        bid=100.0,
        ask=100.1,
        last=100.05,
        mark=100.05,
        source=IBKR_WEBAPI_MARKET_SOURCE_ID,
        exchange_ts=T0,
        received_ts=T0,
        age_ms=0,
        spread_abs=0.1,
        spread_bps=(0.1 / 100.05) * 10_000.0,
        session_state=SessionState.FOCUS,
        quality_state=QualityState.HEALTHY,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="test",
    )


def _binding() -> RuntimeRegistryBinding:
    return RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=CONID,
        shortability_provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        shortability_stale_threshold_ms=1500,
        source_ref="test",
    )


def test_equity_market_binding_and_long_path_do_not_require_locate_truth() -> None:
    binding = RuntimeRegistryBinding(
        asset_id="nvda",
        broker_symbol="NVDA",
        primary_market_source_id=IBKR_WEBAPI_MARKET_SOURCE_ID,
        stale_threshold_ms=1500,
        calendar_provider_id="tradinghours_v3",
        calendar_market_id="US.NASDAQ",
        market_data_contract_id=CONID,
        shortability_provider_id=None,
        shortability_stale_threshold_ms=None,
        source_ref="long-only-market-test",
    )

    blockers = binding_blockers(binding)
    assert "shortability_provider_missing" not in blockers
    assert "shortability_stale_threshold_missing" not in blockers

    row = materialize_bound_registry_row(binding, as_of_utc=T0)
    assert row.market_data_ready() is True
    assert row.product_side_supported("long") is True

    strict = binding_blockers(
        binding,
        require_shortability_provider_implementation=True,
    )
    assert "shortability_provider_missing" in strict
    assert "shortability_stale_threshold_missing" in strict


def _engine_store(*, with_evidence: bool):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg",
                policy_version="policy-v1",
                effective_at_utc=T0 - timedelta(days=1),
                changed_by="test",
                change_reason="shortability test",
                payload={},
                created_at_utc=T0 - timedelta(days=1),
            )
        )
        binding = _binding()
        digest = store.upsert_runtime_registry_binding(
            conn,
            binding,
            registry_version="shortability-test-v1",
            configuration_hash="cfg",
            updated_at_utc=T0,
        )
        store.record_market_observation(conn, _observation())
        conn.execute(
            store.tables["exit_plans"].insert().values(
                exit_plan_id="exit-nvda",
                version="v1",
                hard_stop_price=105.0,
                structure_rule_id=None,
                time_stop_deadline_utc=None,
                trailing_policy={
                    "enabled": False,
                    "start_condition": None,
                    "ratchet_rule": None,
                    "never_loosen": True,
                },
                profit_take_policy={"enabled": False, "rule_id": None},
                session_close_policy="hold",
                stale_mark_policy="hold",
                governor_halt_behavior="hold",
                created_from_playbook_version="1.4",
                payload_hash="hash-exit-nvda",
                created_at_utc=T0,
            )
        )
        conn.execute(
            store.tables["tickets"].insert().values(
                ticket_id="ticket-nvda-short",
                exit_plan_id="exit-nvda",
                setup_id="setup-nvda-short",
                firm_event_id=None,
                asset_id="nvda",
                route_id="nvda:intraday:short",
                state="READY",
                signal_key="signal-nvda-short",
                side="short",
                horizon="intraday",
                stop_price=105.0,
                quantity=1.0,
                modeled_round_trip_cost_pct=0.10,
                reject_code=None,
                policy_version="policy-v1",
                configuration_hash="cfg",
                market_observation_id="obs-nvda",
                first_killed_by=None,
                first_kill_reason=None,
                created_at_utc=T0,
            )
        )
        if with_evidence:
            store.record_shortability_evidence(
                conn,
                _evidence(shares=100),
                configuration_hash="cfg",
                runtime_registry_binding_hash=digest,
                created_at_utc=T0,
            )
    return engine, store


def _reserve_short(conn, store: VNextStore):
    idem = open_intent_idempotency_key(
        ticket_id="ticket-nvda-short",
        side="short",
        quantity=1.0,
        asset_id="nvda",
        horizon="intraday",
        signal_key="signal-nvda-short",
    )
    return store.reserve_risk_checked_open_intent(
        conn,
        order_intent_id="intent-nvda-short",
        ticket_id="ticket-nvda-short",
        firm_event_id=None,
        asset_id="nvda",
        route_id="nvda:intraday:short",
        broker_account_id="ibkr_paper",
        broker="IBKR",
        venue="IBKR",
        symbol="NVDA",
        side="short",
        qty=1.0,
        order_type="MARKET_PAPER",
        reference_price=None,
        expected_fill=None,
        idempotency_key=idem,
        signal_key="signal-nvda-short",
        position_key="nvda:intraday",
        reserve_cash_usd=None,
        reserve_margin_usd=None,
        ready_spread_bps=10.0,
        hard_stop_price=105.0,
        exit_plan_id="exit-nvda",
        submit_timeout_at=None,
        policy_version="policy-v1",
        configuration_hash="cfg",
        market_observation_id="obs-nvda",
        created_at_utc=T0 + timedelta(milliseconds=500),
        event_id="evt-nvda-short",
        actor="portfolio",
        risk_cluster_id=cluster_for_asset("nvda"),
        cluster_by_asset={"nvda": cluster_for_asset("nvda")},
        current_observations={"nvda": _observation()},
    )


def test_durable_shortability_evidence_is_binding_hash_scoped() -> None:
    engine, store = _engine_store(with_evidence=True)
    with engine.begin() as conn:
        runtime = store.load_runtime_registry_binding(conn, asset_id="nvda")
        assert runtime is not None
        loaded = store.latest_shortability_evidence(
            conn,
            asset_id="nvda",
            configuration_hash="cfg",
            runtime_registry_binding_hash=runtime["binding_hash"],
        )
        assert loaded is not None
        assert loaded.evidence_id == _evidence(shares=100).evidence_id
        assert loaded.shortable_shares == 100


def test_phase_a_equity_short_fails_without_durable_locate_evidence() -> None:
    engine, store = _engine_store(with_evidence=False)
    with engine.begin() as conn:
        result = _reserve_short(conn, store)
        assert result["ok"] is False
        assert result["reject_code"] == "product_side_unsupported"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one() == 0


def test_phase_a_equity_short_reserves_only_with_fresh_sufficient_evidence() -> None:
    engine, store = _engine_store(with_evidence=True)
    with engine.begin() as conn:
        result = _reserve_short(conn, store)
        assert result["ok"] is True
        assert result["state"] == "RESERVED"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            )
        ).scalar_one() == 1

        intent = conn.execute(
            sa.select(store.tables["order_intents"]).where(
                store.tables["order_intents"].c.order_intent_id
                == "intent-nvda-short"
            )
        ).mappings().one()
        assert intent["shortability_evidence_id"] == _evidence(
            shares=100
        ).evidence_id

        loaded = store.load_order_intent(
            conn,
            order_intent_id="intent-nvda-short",
        )
        assert loaded is not None
        assert loaded.shortability_evidence_id == intent[
            "shortability_evidence_id"
        ]
