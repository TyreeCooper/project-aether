from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.book_reconciliation_evidence import (
    active_position_identity_issues,
    broker_ledger_issues,
    collect_book_reconciliation_evidence,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 21, 30, tzinfo=UTC)


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
    return engine, store


def test_clean_seed_book_collects_verified_non_synthetic_evidence() -> None:
    engine, store = _engine_store()
    with engine.connect() as conn:
        collected = collect_book_reconciliation_evidence(
            conn,
            store=store,
            evidence_id="book-evidence-1",
            deployed_revision="revision-1",
            observed_at_utc=T0,
            source_artifact_ids=("book-run-1",),
        )

    assert collected.verified is True
    assert collected.evidence.risk_admission_issues == ()
    assert collected.evidence.stale_order_intent_ids == ()
    assert collected.active_position_identity_issues == ()
    assert collected.broker_ledger_issues == ()
    assert collected.evidence.synthetic is False


def test_missing_seed_sleeve_blocks_broker_ledger_evidence() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        conn.execute(
            store.tables["broker_account_ledgers"].delete().where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        )

    with engine.connect() as conn:
        collected = collect_book_reconciliation_evidence(
            conn,
            store=store,
            evidence_id="book-evidence-missing-ledger",
            deployed_revision="revision-1",
            observed_at_utc=T0,
            source_artifact_ids=("book-run-2",),
        )

    assert collected.verified is False
    assert collected.evidence.broker_ledger_balanced is False
    assert collected.broker_ledger_issues == (
        "broker_ledger_missing:kraken_paper",
    )


def test_durable_nonclean_reconciliation_state_blocks_ledger() -> None:
    rows = (
        {
            "broker_account_id": "kraken_paper",
            "cash_available_usd": 1.0,
            "cash_reserved_usd": 0.0,
            "margin_used_usd": 0.0,
            "margin_available_usd": 1.0,
            "reconciliation_state": "desync",
            "row_version": 1,
        },
        {
            "broker_account_id": "tastyfx_paper",
            "cash_available_usd": 1.0,
            "cash_reserved_usd": 0.0,
            "margin_used_usd": 0.0,
            "margin_available_usd": 1.0,
            "reconciliation_state": "clean",
            "row_version": 1,
        },
        {
            "broker_account_id": "ninja_paper",
            "cash_available_usd": 1.0,
            "cash_reserved_usd": 0.0,
            "margin_used_usd": 0.0,
            "margin_available_usd": 1.0,
            "reconciliation_state": "clean",
            "row_version": 1,
        },
        {
            "broker_account_id": "ibkr_paper",
            "cash_available_usd": 1.0,
            "cash_reserved_usd": 0.0,
            "margin_used_usd": 0.0,
            "margin_available_usd": 1.0,
            "reconciliation_state": "clean",
            "row_version": 1,
        },
    )

    assert broker_ledger_issues(rows) == (
        "broker_ledger_reconciliation_not_clean:kraken_paper",
    )


def test_active_position_identity_helper_surfaces_exact_drift() -> None:
    active = (
        {
            "position_key": "btc:1h",
            "trade_id": "trade-1",
            "asset_id": "btc",
            "side": "long",
            "quantity": 0.01,
        },
    )
    trades = (
        {
            "position_key": "btc:1h",
            "trade_id": "trade-1",
            "asset_id": "eth",
            "side": "long",
            "quantity": 0.01,
        },
    )

    assert active_position_identity_issues(
        active_rows=active,
        trade_rows=trades,
        closed_trade_ids=frozenset(),
    ) == ("active_position_asset_mismatch:btc:1h:trade-1",)


def test_active_position_cannot_remain_active_after_trade_is_closed() -> None:
    active = (
        {
            "position_key": "btc:1h",
            "trade_id": "trade-1",
            "asset_id": "btc",
            "side": "long",
            "quantity": 0.01,
        },
    )
    trades = (
        {
            "position_key": "btc:1h",
            "trade_id": "trade-1",
            "asset_id": "btc",
            "side": "long",
            "quantity": 0.01,
        },
    )

    assert active_position_identity_issues(
        active_rows=active,
        trade_rows=trades,
        closed_trade_ids=frozenset({"trade-1"}),
    ) == (
        "active_position_references_closed_trade:btc:1h:trade-1",
    )
