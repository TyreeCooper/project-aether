"""Immutable prototype forward-paper strategy-observation evidence.

This module records natural NO_SETUP decisions produced by the live PAPER crypto
strategy, including seed BTC/ETH and commissioned dynamic Kraken products. These
observations are operational forward-paper audit evidence only:
they are not held-out research evidence and must never satisfy Phase 18 gates.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.freeze import CONFIGURATION_HASH, LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.store import VNextStore


AGGREGATE_TYPE = "prototype_strategy_observation"
SAMPLE_DOMAIN = "prototype_forward_paper_observation"


def _supports_prototype_observation_asset(asset_id: str) -> bool:
    """Bound this evidence lane to the currently commissioned PAPER crypto route."""
    asset = str(asset_id).strip().lower()
    return asset in {"btc", "eth"} or (
        asset.startswith("kraken:") and len(asset) > len("kraken:")
    )


def prototype_strategy_observation_event_id(
    *,
    paper_epoch_id: str,
    asset_id: str,
    trigger_close_utc: datetime,
    reason: str,
) -> str:
    if trigger_close_utc.tzinfo is None:
        raise ValueError("trigger_close_utc must be timezone-aware")
    parts = (
        str(paper_epoch_id).strip(),
        str(asset_id).strip().lower(),
        trigger_close_utc.isoformat(),
        str(reason).strip(),
        CONFIGURATION_HASH,
    )
    if any(not value for value in parts):
        raise ValueError("prototype strategy observation identity is incomplete")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"evt-prototype-observation-{digest}"


def _policy_version(conn: Connection, store: VNextStore) -> str:
    table = store.tables["policy_snapshots"]
    row = conn.execute(
        sa.select(table.c.policy_version).where(
            table.c.configuration_hash == CONFIGURATION_HASH
        )
    ).first()
    if row is None:
        raise RuntimeError("prototype forward-paper evidence requires frozen policy snapshot")
    value = str(row[0]).strip()
    if not value:
        raise RuntimeError("prototype forward-paper policy_version is blank")
    return value


def count_prototype_no_setup_observations(
    conn: Connection,
    store: VNextStore,
    *,
    paper_epoch_id: str,
) -> int:
    epoch = str(paper_epoch_id).strip()
    if not epoch:
        raise ValueError("paper_epoch_id is required")
    events = store.tables["event_ledger"]
    value = conn.execute(
        sa.select(sa.func.count())
        .select_from(events)
        .where(
            events.c.aggregate_type == AGGREGATE_TYPE,
            events.c.aggregate_id.like(f"{epoch}:%"),
        )
    ).scalar_one()
    return int(value)


def persist_prototype_no_setup_observation(
    conn: Connection,
    store: VNextStore,
    *,
    paper_epoch_id: str,
    asset_id: str,
    trigger_close_utc: datetime,
    evaluated_at_utc: datetime,
    market_observation_id: str,
    reason: str,
    watch_eligible: bool,
    volatility_percentile: float | None,
    setup_id: str,
    ticket_id: str,
    order_intent_id: str,
) -> bool:
    """Persist one immutable natural NO_SETUP observation per closed trigger bar.

    Returns True when inserted and False when this exact closed-bar observation was
    already recorded. A duplicate does not create a second event even if a later
    supervisor cycle has a newer executable quote.
    """
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype forward-paper evidence requires PAPER_ONLY/LIVE_BLOCKED")
    if trigger_close_utc.tzinfo is None or evaluated_at_utc.tzinfo is None:
        raise ValueError("prototype evidence timestamps must be timezone-aware")
    if evaluated_at_utc < trigger_close_utc:
        raise ValueError("prototype evidence cannot predate trigger close")
    asset = str(asset_id).strip().lower()
    if not _supports_prototype_observation_asset(asset):
        raise ValueError(
            "prototype forward-paper evidence supports seed btc/eth and "
            "commissioned Kraken assets only"
        )
    epoch = str(paper_epoch_id).strip()
    reason_text = str(reason).strip()
    observation_id = str(market_observation_id).strip()
    if not epoch or not reason_text or not observation_id:
        raise ValueError("prototype forward-paper evidence identity is incomplete")
    if watch_eligible is not False:
        raise ValueError("NO_SETUP evidence requires watch_eligible=false")

    event_id = prototype_strategy_observation_event_id(
        paper_epoch_id=epoch,
        asset_id=asset,
        trigger_close_utc=trigger_close_utc,
        reason=reason_text,
    )
    events = store.tables["event_ledger"]
    existing = conn.execute(
        sa.select(events.c.event_id).where(events.c.event_id == event_id)
    ).first()
    if existing is not None:
        return False

    payload: Mapping[str, Any] = {
        "paper_epoch_id": epoch,
        "asset_id": asset,
        "horizon": "daily_swing",
        "playbook_id": "pb_crypto_swing_v1_2",
        "trigger_close_utc": trigger_close_utc.isoformat(),
        "evaluated_at_utc": evaluated_at_utc.isoformat(),
        "stage": "NO_SETUP",
        "reason": reason_text,
        "watch_eligible": False,
        "volatility_percentile": volatility_percentile,
        "setup_id": str(setup_id),
        "ticket_id": str(ticket_id),
        "order_intent_id": str(order_intent_id),
        "sample_domain": SAMPLE_DOMAIN,
        "natural_setup_only": True,
        "forced_entry_enabled": False,
        "real_market_time_required": True,
        "pit_inputs_required": True,
        "paper_only": True,
        "live_blocked": True,
        "phase18_evidence": False,
    }
    store.append_event(
        conn,
        event_id=event_id,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=f"{epoch}:{asset}:{trigger_close_utc.isoformat()}",
        prior_state=None,
        new_state="NO_SETUP",
        seat="Scout",
        reason_code=ReasonCode.NO_SETUP.value,
        policy_version=_policy_version(conn, store),
        configuration_hash=CONFIGURATION_HASH,
        market_observation_id=observation_id,
        actor="prototype_strategy_supervisor",
        created_at_utc=evaluated_at_utc,
        payload=payload,
    )
    return True
