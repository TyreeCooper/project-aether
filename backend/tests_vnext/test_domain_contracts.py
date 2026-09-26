from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import hashlib

import pytest

from aether_vnext.domain import (
    BrokerAccountLedger,
    EventLedgerRecord,
    SleeveInventoryRecord,
    MarketObservation,
    OrderIntent,
    PolicySnapshot,
    QualityState,
    SessionState,
)
from aether_vnext.freeze import EvidenceState, ResearchState
from aether_vnext.news import (
    HistoricalAnalogRun,
    RawNewsItem,
    raw_news_identity_key,
)
from aether_vnext.research import (
    EvidenceWindow,
    FoldResult,
    ResearchDatasetSnapshot,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 25, 23, 41, tzinfo=UTC)


def test_market_observation_contains_master_truth_fields() -> None:
    names = {f.name for f in fields(MarketObservation)}
    assert {
        "observation_id",
        "asset_id",
        "venue",
        "bid",
        "ask",
        "last",
        "mark",
        "source",
        "exchange_ts",
        "received_ts",
        "age_ms",
        "spread_abs",
        "spread_bps",
        "session_state",
        "quality_state",
        "fallback_reason",
        "calendar_state",
        "data_version",
    } <= names


def test_order_intent_contains_live_shaped_execution_fields() -> None:
    names = {f.name for f in fields(OrderIntent)}
    assert {
        "order_intent_id",
        "lineage",
        "broker",
        "venue",
        "symbol_executed",
        "side",
        "requested_qty",
        "order_type",
        "reference_price",
        "expected_fill_price",
        "submitted_at",
        "acknowledged_at",
        "filled_at",
        "filled_qty",
        "avg_fill_price",
        "reject_code",
        "slip_usd",
        "slip_bps",
        "idempotency_key",
        "broker_account_id",
        "intent_kind",
        "exit_reason",
        "position_key",
        "signal_key",
        "reserved_cash_usd",
        "reserved_margin_usd",
        "ready_spread_bps",
        "hard_stop_price",
        "submit_timeout_at",
        "observation_id_at_reserve",
        "observation_id_at_fill",
        "trade_id",
        "version",
    } <= names


def test_broker_account_ledger_and_inventory_cover_v421_sleeve_fields() -> None:
    ledger_names = {f.name for f in fields(BrokerAccountLedger)}
    assert {
        "broker_account_id",
        "cash_available_usd",
        "cash_reserved_usd",
        "margin_used_usd",
        "margin_available_usd",
        "realized_pnl_usd",
        "unrealized_pnl_usd",
        "fees_accrued_usd",
        "carry_accrued_usd",
        "settled_cash_usd",
        "last_reconciled_at",
        "reconciliation_state",
    } <= ledger_names
    assert "inventory_qty" not in ledger_names
    assert "inventory_avg" not in ledger_names

    inventory_names = {f.name for f in fields(SleeveInventoryRecord)}
    assert {
        "broker_account_id",
        "asset_id",
        "inventory_qty",
        "inventory_avg",
        "updated_at_utc",
        "row_version",
    } <= inventory_names


def test_policy_snapshot_and_event_ledger_keep_configuration_lineage() -> None:
    assert {f.name for f in fields(PolicySnapshot)} >= {
        "policy_version",
        "configuration_hash",
        "effective_at_utc",
        "changed_by",
        "change_reason",
    }
    assert {f.name for f in fields(EventLedgerRecord)} >= {
        "event_id",
        "aggregate_type",
        "aggregate_id",
        "prior_state",
        "new_state",
        "seat",
        "reason_code",
        "policy_version",
        "configuration_hash",
        "market_observation_id",
        "actor",
        "created_at_utc",
        "payload_hash",
    }


def test_market_quality_and_session_values_match_master_contract() -> None:
    assert [x.value for x in QualityState] == [
        "healthy",
        "degraded",
        "stale",
        "invalid",
    ]
    assert [x.value for x in SessionState] == [
        "active",
        "focus",
        "closed",
        "maintenance",
        "halt",
    ]


def test_research_dataset_snapshot_requires_point_in_time_truth() -> None:
    with pytest.raises(ValueError):
        ResearchDatasetSnapshot(
            dataset_snapshot_id="d1",
            created_at_utc=NOW,
            as_of_utc=NOW,
            start_at_utc=NOW,
            end_at_utc=NOW,
            asset_ids=("btc",),
            data_version="v1",
            source_registry_version="v1",
            product_registry_version="v1",
            calendar_version="v1",
            pit=False,
            missing_data_policy="defer",
            content_hash="abc",
        )


def test_fold_result_rejects_non_chronological_windows() -> None:
    with pytest.raises(ValueError):
        FoldResult(
            fold_result_id="f1",
            backtest_run_id="b1",
            fold_index=1,
            train_start_utc=NOW,
            train_end_utc=NOW,
            test_start_utc=NOW,
            test_end_utc=NOW,
            n=1,
            net_pnl=0,
            expectancy_r=0,
            profit_factor=1,
            stop_rate=0,
            max_drawdown=0,
            cost_drag=0,
            benchmark_result={},
            passed=False,
        )


def test_evidence_window_keeps_sample_domains_separate() -> None:
    good = EvidenceWindow(
        evidence_window_id="e1",
        route_id="eurusd:intraday:long",
        playbook_version="1.3",
        policy_configuration_hash_family="cfg",
        sample_domain="paper_forward",
        first_timestamp_utc=NOW,
        last_timestamp_utc=NOW,
        n=1,
        immutable_trade_ids=("t1",),
        metrics_snapshot_hash="m1",
    )
    assert good.sample_domain == "paper_forward"
    with pytest.raises(ValueError):
        EvidenceWindow(
            evidence_window_id="e2",
            route_id="eurusd:intraday:long",
            playbook_version="1.3",
            policy_configuration_hash_family="cfg",
            sample_domain="mixed",
            first_timestamp_utc=NOW,
            last_timestamp_utc=NOW,
            n=1,
            immutable_trade_ids=("t1",),
            metrics_snapshot_hash="m2",
        )


def test_raw_news_item_contains_all_frozen_publication_time_fields() -> None:
    names = {f.name for f in fields(RawNewsItem)}
    assert {
        "published_at_utc",
        "first_seen_at_utc",
        "received_at_utc",
        "revision_of_news_item_id",
        "correction_or_retraction",
        "dedupe_key",
        "raw_payload_ref",
    } <= names


def test_historical_analog_is_research_only_and_point_in_time_bounded() -> None:
    run = HistoricalAnalogRun(
        analog_run_id="a1",
        query_event_or_state_id="q1",
        feature_spec_version="v1",
        as_of_utc=NOW,
        eligible_history_cutoff_utc=NOW,
        matched_event_ids=("e1",),
        similarity_scores=(0.9,),
        outcome_distribution={"median_return": 0.01},
        created_at_utc=NOW,
    )
    assert run.research_only is True


def test_news_identity_prefers_provider_id_and_hashes_it() -> None:
    key = raw_news_identity_key(
        source_id="reuters",
        provider_item_id="abc",
        canonical_url="https://example.com/x",
        published_at_utc=NOW,
        normalized_title="hello",
    )
    expected = hashlib.sha256(b"reuters|abc").hexdigest()
    assert key == expected


def test_research_and_evidence_states_remain_separate_types() -> None:
    assert ResearchState.FROZEN.value == "FROZEN"
    assert EvidenceState.CANDIDATE.value == "CANDIDATE"
    assert ResearchState.FROZEN.__class__ is not EvidenceState.CANDIDATE.__class__
