"""Start a C9.1 forward-paper burn-in campaign from the vNext book.

This service does not create a new trading mode. It freezes the current canonical
configuration and an explicit caller-declared route/playbook set against all matching
held-out EvidenceWindows already present in the vNext book. Missing evidence fails the
entire start before any campaign row is written.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.evidence import SampleDomain
from aether_vnext.forward_paper import (
    ForwardPaperCampaign,
    ForwardPaperRouteBaseline,
    parse_route_id,
)
from aether_vnext.freeze import (
    CONFIGURATION_HASH,
    FORCED_ENTRIES_STRATEGY_TEST,
    LIVE_BLOCKED,
    PAPER_ONLY,
)
from aether_vnext.playbooks import playbook
from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class ForwardPaperRouteRequest:
    route_id: str
    playbook_id: str

    def __post_init__(self) -> None:
        if not str(self.route_id).strip():
            raise ValueError("route_id is required")
        if not str(self.playbook_id).strip():
            raise ValueError("playbook_id is required")


@dataclass(frozen=True, slots=True)
class ForwardPaperStartResult:
    campaign: ForwardPaperCampaign
    routes: tuple[ForwardPaperRouteBaseline, ...]

    @property
    def baseline_snapshot_hash(self) -> str:
        return self.campaign.baseline_snapshot_hash


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _route_baseline_hash(
    *,
    route_id: str,
    playbook_id: str,
    playbook_version: str,
    configuration_hash: str,
    rows: tuple[dict[str, object], ...],
) -> str:
    return _canonical_hash(
        {
            "route_id": route_id,
            "playbook_id": playbook_id,
            "playbook_version": playbook_version,
            "configuration_hash": configuration_hash,
            "held_out_windows": [
                {
                    "evidence_window_id": str(row["evidence_window_id"]),
                    "metrics_snapshot_hash": str(row["metrics_snapshot_hash"]),
                    "first_timestamp_utc": row["first_timestamp_utc"].isoformat(),
                    "last_timestamp_utc": row["last_timestamp_utc"].isoformat(),
                    "n": int(row["n"]),
                    "immutable_trade_ids": list(
                        row["immutable_trade_ids"] or []
                    ),
                }
                for row in rows
            ],
        }
    )


def start_forward_paper_campaign_from_book(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    requested_routes: tuple[ForwardPaperRouteRequest, ...],
    started_at_utc: datetime,
    created_at_utc: datetime,
) -> ForwardPaperStartResult:
    """Freeze an explicit burn-in route set against current held-out evidence.

    The canonical configuration hash is not caller-selectable. Every requested route
    must have at least one held-out window in the current configuration/policy family.
    All matching held-out windows are frozen into the baseline to avoid cherry-picking.
    """
    if not str(campaign_id).strip():
        raise ValueError("campaign_id is required")
    if not requested_routes:
        raise ValueError("requested_routes cannot be empty")
    if started_at_utc.tzinfo is None or created_at_utc.tzinfo is None:
        raise ValueError("campaign timestamps must be timezone-aware")

    if not PAPER_ONLY:
        raise RuntimeError("forward-paper burn-in requires PAPER_ONLY")
    if not LIVE_BLOCKED:
        raise RuntimeError("forward-paper burn-in requires LIVE_BLOCKED")
    if FORCED_ENTRIES_STRATEGY_TEST:
        raise RuntimeError(
            "forward-paper burn-in requires forced strategy entries OFF"
        )

    policies = store.tables["policy_snapshots"]
    policy = conn.execute(
        sa.select(policies).where(
            policies.c.configuration_hash == CONFIGURATION_HASH
        )
    ).mappings().first()
    if policy is None:
        raise RuntimeError(
            "current canonical configuration has no durable policy snapshot"
        )
    policy_version = str(policy["policy_version"])

    seen: set[tuple[str, str]] = set()
    for request in requested_routes:
        key = (request.route_id, request.playbook_id)
        if key in seen:
            raise ValueError("duplicate route/playbook request")
        seen.add(key)

    evidence = store.tables["evidence_windows"]
    route_baselines: list[ForwardPaperRouteBaseline] = []
    baseline_payload: list[dict[str, object]] = []

    for request in sorted(
        requested_routes,
        key=lambda item: (item.route_id, item.playbook_id),
    ):
        spec = playbook(request.playbook_id)
        if not spec.scout_definition_enabled:
            raise ValueError(
                f"playbook is not burn-in eligible: {request.playbook_id}"
            )

        asset_id, horizon, side = parse_route_id(request.route_id)
        if asset_id not in spec.allowed_assets:
            raise ValueError("requested route asset not allowed by playbook")
        if horizon != spec.horizon:
            raise ValueError("requested route horizon mismatch")
        if side not in spec.allowed_sides:
            raise ValueError("requested route side not allowed by playbook")

        rows = tuple(
            dict(row)
            for row in conn.execute(
                sa.select(evidence)
                .where(
                    sa.and_(
                        evidence.c.route_id == request.route_id,
                        evidence.c.playbook_id == request.playbook_id,
                        evidence.c.playbook_version == spec.version,
                        evidence.c.configuration_hash == CONFIGURATION_HASH,
                        evidence.c.policy_version == policy_version,
                        evidence.c.sample_domain
                        == SampleDomain.HELD_OUT.value,
                    )
                )
                .order_by(
                    evidence.c.first_timestamp_utc.asc(),
                    evidence.c.last_timestamp_utc.asc(),
                    evidence.c.evidence_window_id.asc(),
                )
            ).mappings()
        )
        if not rows:
            raise RuntimeError(
                "requested burn-in route has no current held-out baseline: "
                f"{request.route_id}|{request.playbook_id}"
            )

        route_hash = _route_baseline_hash(
            route_id=request.route_id,
            playbook_id=request.playbook_id,
            playbook_version=spec.version,
            configuration_hash=CONFIGURATION_HASH,
            rows=rows,
        )
        window_ids = tuple(
            str(row["evidence_window_id"])
            for row in rows
        )
        campaign_route_id = _canonical_hash(
            {
                "campaign_id": campaign_id,
                "route_id": request.route_id,
                "playbook_id": request.playbook_id,
                "playbook_version": spec.version,
                "configuration_hash": CONFIGURATION_HASH,
            }
        )

        route = ForwardPaperRouteBaseline(
            campaign_route_id=campaign_route_id,
            campaign_id=campaign_id,
            route_id=request.route_id,
            playbook_id=request.playbook_id,
            playbook_version=spec.version,
            configuration_hash=CONFIGURATION_HASH,
            historical_validation_window_ids=window_ids,
            historical_metrics_snapshot_hash=route_hash,
        )
        route_baselines.append(route)
        baseline_payload.append(
            {
                "campaign_route_id": campaign_route_id,
                "route_id": request.route_id,
                "playbook_id": request.playbook_id,
                "playbook_version": spec.version,
                "historical_validation_window_ids": list(window_ids),
                "historical_metrics_snapshot_hash": route_hash,
            }
        )

    baseline_snapshot_hash = _canonical_hash(
        {
            "configuration_hash": CONFIGURATION_HASH,
            "policy_version": policy_version,
            "routes": baseline_payload,
        }
    )
    campaign = ForwardPaperCampaign(
        campaign_id=campaign_id,
        configuration_hash=CONFIGURATION_HASH,
        policy_version=policy_version,
        baseline_snapshot_hash=baseline_snapshot_hash,
        started_at_utc=started_at_utc,
        created_at_utc=created_at_utc,
    )

    store.record_forward_paper_campaign(
        conn,
        campaign,
        routes=tuple(route_baselines),
    )
    return ForwardPaperStartResult(
        campaign=campaign,
        routes=tuple(route_baselines),
    )
