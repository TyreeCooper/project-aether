"""Read-only runtime-book health checks shared by burn-in gates."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.engine import Connection

from aether_vnext.store import VNextStore


def runtime_book_blockers(
    conn: Connection,
    *,
    store: VNextStore,
    as_of_utc: datetime,
) -> tuple[str, ...]:
    """Return fail-closed blockers for unsafe or unreconciled runtime book state."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    blockers = [
        f"risk_admission_reconciliation:{issue}"
        for issue in store.risk_admission_reconciliation_issues(conn)
    ]
    if store.stale_order_intent_ids(conn, at_utc=as_of_utc):
        blockers.append("stale_order_intents_present")
    return tuple(blockers)
