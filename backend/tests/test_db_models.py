from app.db.base import Base
from app.db import models  # noqa: F401


def test_core_ledger_tables_are_registered():
    names = set(Base.metadata.tables)

    assert {
        "orders",
        "fills",
        "positions",
        "account_snapshots",
        "audit_events",
        "strategy_configs",
        "risk_configs",
        "reconcile_events",
    }.issubset(names)


def test_order_client_id_is_unique():
    table = Base.metadata.tables["orders"]
    assert table.c.client_order_id.unique is True
