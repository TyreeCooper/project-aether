"""Read-only forward-paper burn-in preflight.

This module inspects the vNext book and produces the exact campaign baseline that would
be used by start_forward_paper_campaign_from_book(). It performs no writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.evidence import SampleDomain, independent_n
from aether_vnext.forward_paper import ForwardPaperRouteBaseline, parse_route_id
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
class ForwardPaperRoutePreflight:
    request: ForwardPaperRouteRequest
    eligible: bool
    playbook_version: str | None
    held_out_window_ids: tuple[str, ...]
    held_out_window_count: int
    independent_held_out_n: int
    route_baseline_hash: str | None
    campaign_route_id: str | None
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForwardPaperPreflightResult:
    campaign_id: str
    configuration_hash: str
    policy_version: str | None
    requested_route_count: int
    startable: bool
    route_results: tuple[ForwardPaperRoutePreflight, ...]
    baseline_snapshot_hash: str | None
    blockers: tuple[str, ...]

    @property
    def missing_routes(self) -> tuple[str, ...]:
        return tuple(
            row.request.route_id
            for row in self.route_results
            if "missing_current_held_out_baseline" in row.blockers
        )


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


def preflight_forward_paper_campaign_from_book(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    requested_routes: tuple[ForwardPaperRouteRequest, ...],
) -> ForwardPaperPreflightResult:
    """Inspect whether the current vNext book can start a C9.1 campaign."""
    if not str(campaign_id).strip():
        raise ValueError("campaign_id is required")
    if not requested_routes:
        raise ValueError("requested_routes cannot be empty")

    blockers: list[str] = []
    if not PAPER_ONLY:
        blockers.append("paper_only_not_enabled")
    if not LIVE_BLOCKED:
        blockers.append("live_not_blocked")
    if FORCED_ENTRIES_STRATEGY_TEST:
        blockers.append("forced_strategy_entries_enabled")

    policies = store.tables["policy_snapshots"]
    policy = conn.execute(
        sa.select(policies).where(
            policies.c.configuration_hash == CONFIGURATION_HASH
        )
    ).mappings().first()
    policy_version = str(policy["policy_version"]) if policy is not None else None
    if policy is None:
        blockers.append("canonical_policy_snapshot_missing")

    seen: set[tuple[str, str]] = set()
    route_results: list[ForwardPaperRoutePreflight] = []
    baseline_payload: list[dict[str, object]] = []
    evidence = store.tables["evidence_windows"]

    for request in sorted(
        requested_routes,
        key=lambda item: (item.route_id, item.playbook_id),
    ):
        route_blockers: list[str] = []
        key = (request.route_id, request.playbook_id)
        if key in seen:
            route_blockers.append("duplicate_route_playbook_request")
        seen.add(key)

        spec = None
        try:
            spec = playbook(request.playbook_id)
        except KeyError:
            route_blockers.append("unknown_playbook")

        if spec is not None and not spec.scout_definition_enabled:
            route_blockers.append("playbook_not_burnin_eligible")

        if spec is not None:
            try:
                asset_id, horizon, side = parse_route_id(request.route_id)
                if asset_id not in spec.allowed_assets:
                    route_blockers.append("asset_not_allowed_by_playbook")
                if horizon != spec.horizon:
                    route_blockers.append("horizon_mismatch")
                if side not in spec.allowed_sides:
                    route_blockers.append("side_not_allowed_by_playbook")
            except ValueError:
                route_blockers.append("invalid_route_id")

        rows: tuple[dict[str, object], ...] = ()
        route_hash: str | None = None
        campaign_route_id: str | None = None
        independent_count = 0

        if (
            spec is not None
            and policy_version is not None
            and not route_blockers
        ):
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
                route_blockers.append("missing_current_held_out_baseline")
            else:
                windows = tuple(
                    store.load_evidence_window(
                        conn,
                        evidence_window_id=str(row["evidence_window_id"]),
                    )
                    for row in rows
                )
                if any(window is None for window in windows):
                    route_blockers.append("held_out_window_reload_failed")
                else:
                    concrete = tuple(
                        window for window in windows if window is not None
                    )
                    independent_count = independent_n(concrete)
                    route_hash = _route_baseline_hash(
                        route_id=request.route_id,
                        playbook_id=request.playbook_id,
                        playbook_version=spec.version,
                        configuration_hash=CONFIGURATION_HASH,
                        rows=rows,
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
                    baseline_payload.append(
                        {
                            "campaign_route_id": campaign_route_id,
                            "route_id": request.route_id,
                            "playbook_id": request.playbook_id,
                            "playbook_version": spec.version,
                            "historical_validation_window_ids": [
                                str(row["evidence_window_id"]) for row in rows
                            ],
                            "historical_metrics_snapshot_hash": route_hash,
                        }
                    )

        route_results.append(
            ForwardPaperRoutePreflight(
                request=request,
                eligible=not route_blockers,
                playbook_version=(spec.version if spec is not None else None),
                held_out_window_ids=tuple(
                    str(row["evidence_window_id"]) for row in rows
                ),
                held_out_window_count=len(rows),
                independent_held_out_n=independent_count,
                route_baseline_hash=route_hash,
                campaign_route_id=campaign_route_id,
                blockers=tuple(dict.fromkeys(route_blockers)),
            )
        )

    if any(row.blockers for row in route_results):
        blockers.append("one_or_more_routes_not_startable")

    baseline_snapshot_hash: str | None = None
    if not blockers and policy_version is not None:
        baseline_snapshot_hash = _canonical_hash(
            {
                "configuration_hash": CONFIGURATION_HASH,
                "policy_version": policy_version,
                "routes": baseline_payload,
            }
        )

    return ForwardPaperPreflightResult(
        campaign_id=campaign_id,
        configuration_hash=CONFIGURATION_HASH,
        policy_version=policy_version,
        requested_route_count=len(requested_routes),
        startable=not blockers,
        route_results=tuple(route_results),
        baseline_snapshot_hash=baseline_snapshot_hash,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def route_baselines_from_preflight(
    result: ForwardPaperPreflightResult,
) -> tuple[ForwardPaperRouteBaseline, ...]:
    if not result.startable:
        raise ValueError("preflight is not startable")
    out: list[ForwardPaperRouteBaseline] = []
    for row in result.route_results:
        if (
            row.playbook_version is None
            or row.route_baseline_hash is None
            or row.campaign_route_id is None
        ):
            raise RuntimeError("startable preflight contains incomplete route")
        out.append(
            ForwardPaperRouteBaseline(
                campaign_route_id=row.campaign_route_id,
                campaign_id=result.campaign_id,
                route_id=row.request.route_id,
                playbook_id=row.request.playbook_id,
                playbook_version=row.playbook_version,
                configuration_hash=result.configuration_hash,
                historical_validation_window_ids=row.held_out_window_ids,
                historical_metrics_snapshot_hash=row.route_baseline_hash,
            )
        )
    return tuple(out)
