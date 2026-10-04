"""Idempotent canonical policy bootstrap for an empty vNext burn-in book."""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.freeze import (
    CONFIGURATION_HASH,
    FREEZE_VERSION,
    canonical_freeze_payload,
)
from aether_vnext.store import VNextStore


def bootstrap_canonical_policy_snapshot(
    conn: Connection,
    store: VNextStore,
    *,
    effective_at_utc: datetime,
    created_at_utc: datetime,
) -> bool:
    """Insert the current frozen policy identity once.

    Returns True when inserted and False when an identical canonical row already
    exists. Conflicting content under the canonical hash fails closed.
    """
    if effective_at_utc.tzinfo is None or created_at_utc.tzinfo is None:
        raise ValueError("policy bootstrap timestamps must be timezone-aware")

    table = store.tables["policy_snapshots"]
    existing = conn.execute(
        sa.select(table).where(
            table.c.configuration_hash == CONFIGURATION_HASH
        )
    ).mappings().first()
    payload = canonical_freeze_payload()

    if existing is not None:
        if str(existing["policy_version"]) != FREEZE_VERSION:
            raise RuntimeError(
                "canonical configuration hash exists with another policy_version"
            )
        if dict(existing["payload"] or {}) != payload:
            raise RuntimeError(
                "canonical configuration hash exists with conflicting payload"
            )
        return False

    conflicting_version = conn.execute(
        sa.select(table.c.configuration_hash).where(
            table.c.policy_version == FREEZE_VERSION
        )
    ).scalar_one_or_none()
    if conflicting_version is not None:
        raise RuntimeError(
            "canonical policy_version exists under another configuration hash"
        )

    conn.execute(
        table.insert().values(
            configuration_hash=CONFIGURATION_HASH,
            policy_version=FREEZE_VERSION,
            effective_at_utc=effective_at_utc,
            changed_by="aether_vnext.bootstrap",
            change_reason="canonical pre-code freeze bootstrap",
            payload=payload,
            created_at_utc=created_at_utc,
        )
    )
    return True
