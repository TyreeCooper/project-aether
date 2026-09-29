from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.store import SEED_LEDGER_CASH_USD, VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 22, 40, tzinfo=UTC)


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
    return engine, store


def test_new_paper_epoch_resets_all_four_sleeves_to_canonical_10k() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        ledgers = store.tables["broker_account_ledgers"]
        conn.execute(
            ledgers.update()
            .where(ledgers.c.broker_account_id == "kraken_paper")
            .values(
                cash_available_usd=3123.0,
                cash_reserved_usd=100.0,
                margin_used_usd=50.0,
                margin_available_usd=3850.0,
                realized_pnl_usd=-77.0,
                unrealized_pnl_usd=12.0,
                fees_accrued_usd=9.0,
                carry_accrued_usd=3.0,
                settled_cash_usd=3980.0,
                reconciliation_state="clean",
                row_version=4,
            )
        )
        preview = store.paper_test_reset_preview(conn)
        assert preview["resettable"] is True
        assert preview["seed_bank_total_usd"] == 10_000.0

        epoch = store.start_new_paper_test_epoch(
            conn,
            epoch_id="vnext-new-system-test-001",
            started_at_utc=T0,
            reason="whole new system / whole new tests",
        )
        rows = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }

    assert epoch["seed_bank_total_usd"] == 10_000.0
    assert epoch["paper_only"] is True
    assert epoch["live_blocked"] is True
    for broker_id, seed_cash in SEED_LEDGER_CASH_USD.items():
        row = rows[broker_id]
        assert row["cash_available_usd"] == seed_cash
        assert row["cash_reserved_usd"] == 0.0
        assert row["margin_used_usd"] == 0.0
        assert row["margin_available_usd"] == seed_cash
        assert row["realized_pnl_usd"] == 0.0
        assert row["unrealized_pnl_usd"] == 0.0
        assert row["fees_accrued_usd"] == 0.0
        assert row["carry_accrued_usd"] == 0.0
        assert row["settled_cash_usd"] == seed_cash
        assert row["reconciliation_state"] == "clean"


def test_reset_preserves_prior_state_hash_and_epoch_history() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        preview = store.paper_test_reset_preview(conn)
        first = store.start_new_paper_test_epoch(
            conn,
            epoch_id="epoch-1",
            started_at_utc=T0,
            reason="new system test",
        )
        current = store.current_paper_test_epoch(conn)

    assert first["prior_state_hash"] == preview["prior_state_hash"]
    assert current is not None
    assert current["epoch_id"] == "epoch-1"
    assert current["seed_sleeves"] == dict(SEED_LEDGER_CASH_USD)


def test_reset_is_blocked_if_book_is_not_flat() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        inventory = store.tables["sleeve_inventory"]
        conn.execute(
            inventory.insert().values(
                broker_account_id="kraken_paper",
                asset_id="btc",
                inventory_qty=0.01,
                inventory_avg=50000.0,
                updated_at_utc=T0,
                row_version=1,
            )
        )
        preview = store.paper_test_reset_preview(conn)
        assert preview["resettable"] is False
        assert preview["blockers"] == ("sleeve_inventory:1",)

        with pytest.raises(RuntimeError, match="sleeve_inventory:1"):
            store.start_new_paper_test_epoch(
                conn,
                epoch_id="blocked",
                started_at_utc=T0,
                reason="should fail",
            )

    with engine.connect() as conn:
        assert store.current_paper_test_epoch(conn) is None
        assert sum(
            float(row["cash_available_usd"])
            for row in store.ledger_rows(conn)
        ) == 10_000.0


def test_current_epoch_is_latest_and_blotter_scope_starts_empty() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        store.start_new_paper_test_epoch(
            conn,
            epoch_id="epoch-1",
            started_at_utc=T0,
            reason="first",
        )
        store.start_new_paper_test_epoch(
            conn,
            epoch_id="epoch-2",
            started_at_utc=T0 + timedelta(seconds=1),
            reason="second",
            created_at_utc=T0 + timedelta(seconds=1),
        )
        current = store.current_paper_test_epoch(conn)
        blotter = store.closed_trades_current_paper_epoch(conn)

    assert current is not None
    assert current["epoch_id"] == "epoch-2"
    assert blotter == ()


def test_invalid_blotter_limit_is_rejected() -> None:
    engine, store = _engine_store()
    with engine.connect() as conn:
        with pytest.raises(ValueError, match="positive integer"):
            store.closed_trades_current_paper_epoch(conn, limit=0)
