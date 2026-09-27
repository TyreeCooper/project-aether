"""Bridge one closed-bar runtime decision into durable Scout WATCH setups.

Only WATCH materialization lives here. FIRE, sizing, Clerk, Governor, Risk, and
Execution remain downstream seats.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.engine import Connection

from aether_vnext.domain import Setup
from aether_vnext.regime import RegimeTags
from aether_vnext.runtime_cycle import ClosedBarCycleResult
from aether_vnext.scout import build_watch_setup
from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class WatchMaterialization:
    playbook_id: str
    side: str
    setup_id: str
    firm_event_id: str
    invalidation: float | None
    quality: float | None
    intel_pack: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("playbook_id", "side", "setup_id", "firm_event_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")


def persist_cycle_watch_setups(
    conn: Connection,
    store: VNextStore,
    *,
    cycle: ClosedBarCycleResult,
    materializations: tuple[WatchMaterialization, ...],
    policy_version: str,
    configuration_hash: str,
    market_observation_id: str,
    created_at_utc: datetime,
    regime_tags: RegimeTags,
) -> tuple[Setup, ...]:
    """Persist exactly the WATCH candidates produced by one closed-bar cycle."""
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    if not str(policy_version).strip() or not str(configuration_hash).strip():
        raise ValueError("policy identity is required")
    if not str(market_observation_id).strip():
        raise ValueError("market_observation_id is required")

    candidates = cycle.decision.watch_candidates
    candidate_keys = tuple(
        (candidate.playbook_id, candidate.side)
        for candidate in candidates
    )
    materialization_by_key: dict[tuple[str, str], WatchMaterialization] = {}
    for row in materializations:
        key = (row.playbook_id, row.side)
        if key in materialization_by_key:
            raise ValueError(f"duplicate WATCH materialization: {key}")
        materialization_by_key[key] = row

    supplied_keys = set(materialization_by_key)
    expected_keys = set(candidate_keys)
    if supplied_keys != expected_keys:
        missing = sorted(expected_keys - supplied_keys)
        extra = sorted(supplied_keys - expected_keys)
        raise ValueError(
            f"WATCH materialization mismatch missing={missing} extra={extra}"
        )

    setups: list[Setup] = []
    for candidate in candidates:
        row = materialization_by_key[
            (candidate.playbook_id, candidate.side)
        ]
        setup = build_watch_setup(
            candidate,
            setup_id=row.setup_id,
            firm_event_id=row.firm_event_id,
            policy_version=policy_version,
            configuration_hash=configuration_hash,
            market_observation_id=market_observation_id,
            trigger_bar_close_exchange_ts=cycle.trigger_bar_close_utc,
            created_at_utc=created_at_utc,
            invalidation=row.invalidation,
            quality=row.quality,
            regime_tags=regime_tags,
            intel_pack=row.intel_pack,
        )
        store.record_watch_setup(conn, setup)
        setups.append(setup)

    return tuple(setups)
