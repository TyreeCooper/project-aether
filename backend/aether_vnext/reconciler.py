"""AETHER vNext stale-intent reconciler.

The reconciler is deliberately small: it finds durable RESERVED/SUBMITTED intents
past their 15-second timeout and releases their exact broker-local reservation.
It never creates a replacement intent, never consumes signal_key, and never waits
inside a SQL transaction.
"""
from __future__ import annotations

from datetime import datetime
import hashlib

from sqlalchemy.engine import Connection

from aether_vnext.store import VNextStore


RECONCILER_INTERVAL_SECONDS = 2


def stale_cancel_event_id(
    *,
    order_intent_id: str,
    submit_timeout_at: datetime,
) -> str:
    raw = (
        f"portfolio.stale_cancel|{order_intent_id}|"
        f"{submit_timeout_at.isoformat()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reconcile_stale_intents(
    conn: Connection,
    *,
    store: VNextStore,
    at_utc: datetime,
    actor: str = "execution-reconciler",
) -> tuple[dict, ...]:
    """Cancel every currently stale zero-fill intent in this short transaction."""
    intents = store.tables["order_intents"]
    out: list[dict] = []

    for order_intent_id in store.stale_order_intent_ids(
        conn,
        at_utc=at_utc,
    ):
        row = conn.execute(
            intents.select().where(
                intents.c.order_intent_id == order_intent_id
            )
        ).mappings().one()
        timeout_at = row["submit_timeout_at"]
        if timeout_at is None:
            continue
        result = store.release_order_reservation(
            conn,
            order_intent_id=order_intent_id,
            terminal_state="CANCELLED_STALE",
            reject_code="submit_timeout",
            at_utc=at_utc,
            event_id=stale_cancel_event_id(
                order_intent_id=order_intent_id,
                submit_timeout_at=timeout_at,
            ),
            actor=actor,
            first_killed_by="Portfolio",
        )
        out.append(result)

    return tuple(out)
