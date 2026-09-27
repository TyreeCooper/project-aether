"""Start a C9.1 forward-paper burn-in campaign from the vNext book.

The write path consumes the same read-only preflight result exposed to operators so
inspection and persistence cannot silently disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from aether_vnext.forward_paper import ForwardPaperCampaign, ForwardPaperRouteBaseline
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.forward_paper_preflight import (
    ForwardPaperRouteRequest,
    canonical_forward_paper_route_requests,
    preflight_canonical_forward_paper_campaign_from_book,
    preflight_forward_paper_campaign_from_book,
    route_baselines_from_preflight,
    forward_paper_baseline_snapshot_hash,
)
from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class ForwardPaperStartResult:
    campaign: ForwardPaperCampaign
    routes: tuple[ForwardPaperRouteBaseline, ...]

    @property
    def baseline_snapshot_hash(self) -> str:
        return self.campaign.baseline_snapshot_hash


def _stored_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _load_existing_start_result(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
) -> ForwardPaperStartResult | None:
    campaigns = store.tables["forward_paper_campaigns"]
    row = conn.execute(
        sa.select(campaigns).where(campaigns.c.campaign_id == campaign_id)
    ).mappings().first()
    if row is None:
        return None

    campaign = ForwardPaperCampaign(
        campaign_id=str(row["campaign_id"]),
        configuration_hash=str(row["configuration_hash"]),
        policy_version=str(row["policy_version"]),
        baseline_snapshot_hash=str(row["baseline_snapshot_hash"]),
        started_at_utc=_stored_utc(row["started_at_utc"]),
        created_at_utc=_stored_utc(row["created_at_utc"]),
        forced_entry_enabled=bool(row["forced_entry_enabled"]),
        natural_setup_only=bool(row["natural_setup_only"]),
        real_market_time_required=bool(row["real_market_time_required"]),
        pit_inputs_required=bool(row["pit_inputs_required"]),
        modeled_cost_capture_required=bool(row["modeled_cost_capture_required"]),
        observed_cost_capture_required=bool(row["observed_cost_capture_required"]),
        route_pnl_accounting_required=bool(row["route_pnl_accounting_required"]),
        disposition_accounting_required=bool(row["disposition_accounting_required"]),
        no_cherry_pick=bool(row["no_cherry_pick"]),
        historical_comparison_separate=bool(
            row["historical_comparison_separate"]
        ),
        live_blocked=bool(row["live_blocked"]),
    )

    route_table = store.tables["forward_paper_campaign_routes"]
    route_rows = conn.execute(
        sa.select(route_table)
        .where(route_table.c.campaign_id == campaign_id)
        .order_by(
            route_table.c.route_id.asc(),
            route_table.c.playbook_id.asc(),
            route_table.c.campaign_route_id.asc(),
        )
    ).mappings()
    routes = tuple(
        ForwardPaperRouteBaseline(
            campaign_route_id=str(route["campaign_route_id"]),
            campaign_id=str(route["campaign_id"]),
            route_id=str(route["route_id"]),
            playbook_id=str(route["playbook_id"]),
            playbook_version=str(route["playbook_version"]),
            configuration_hash=str(route["configuration_hash"]),
            runtime_registry_binding_hash=str(
                route["runtime_registry_binding_hash"]
            ),
            historical_validation_window_ids=tuple(
                str(value)
                for value in route["historical_validation_window_ids"]
            ),
            historical_metrics_snapshot_hash=str(
                route["historical_metrics_snapshot_hash"]
            ),
        )
        for route in route_rows
    )
    if not routes:
        raise RuntimeError("existing forward-paper campaign has no routes")
    return ForwardPaperStartResult(campaign=campaign, routes=routes)


def _reuse_existing_campaign(
    existing: ForwardPaperStartResult,
    *,
    requested_routes: tuple[ForwardPaperRouteRequest, ...],
    expected_baseline_snapshot_hash: str | None = None,
) -> ForwardPaperStartResult:
    if existing.campaign.configuration_hash != CONFIGURATION_HASH:
        raise RuntimeError(
            "campaign_id already belongs to a different configuration"
        )
    requested = tuple(
        sorted(
            (request.route_id, request.playbook_id)
            for request in requested_routes
        )
    )
    persisted = tuple(
        sorted((route.route_id, route.playbook_id) for route in existing.routes)
    )
    if persisted != requested:
        raise RuntimeError(
            "campaign_id already belongs to a different route universe"
        )

    if any(
        route.campaign_id != existing.campaign.campaign_id
        or route.configuration_hash != existing.campaign.configuration_hash
        for route in existing.routes
    ):
        raise RuntimeError(
            "existing forward-paper campaign route identity drift"
        )

    persisted_hash = forward_paper_baseline_snapshot_hash(
        configuration_hash=existing.campaign.configuration_hash,
        policy_version=existing.campaign.policy_version,
        routes=existing.routes,
    )
    if persisted_hash != existing.campaign.baseline_snapshot_hash:
        raise RuntimeError(
            "existing forward-paper campaign baseline integrity mismatch"
        )
    if (
        expected_baseline_snapshot_hash is not None
        and existing.campaign.baseline_snapshot_hash
        != expected_baseline_snapshot_hash
    ):
        raise RuntimeError(
            "concurrent campaign start baseline mismatch"
        )
    return existing


def _persist_forward_paper_campaign_from_preflight(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    preflight,
    started_at_utc: datetime,
    created_at_utc: datetime,
) -> ForwardPaperStartResult:
    if not preflight.startable:
        route_detail = ";".join(
            f"{row.request.route_id}|{row.request.playbook_id}:"
            + ",".join(row.blockers)
            for row in preflight.route_results
            if row.blockers
        )
        detail = ",".join(preflight.blockers)
        if route_detail:
            detail = f"{detail};{route_detail}"
        raise RuntimeError(f"forward-paper preflight failed: {detail}")

    if preflight.policy_version is None or preflight.baseline_snapshot_hash is None:
        raise RuntimeError("startable preflight lacks policy/baseline identity")

    routes = route_baselines_from_preflight(preflight)
    campaign = ForwardPaperCampaign(
        campaign_id=campaign_id,
        configuration_hash=preflight.configuration_hash,
        policy_version=preflight.policy_version,
        baseline_snapshot_hash=preflight.baseline_snapshot_hash,
        started_at_utc=started_at_utc,
        created_at_utc=created_at_utc,
    )
    try:
        with conn.begin_nested():
            store.record_forward_paper_campaign(
                conn,
                campaign,
                routes=routes,
            )
    except IntegrityError:
        existing = _load_existing_start_result(
            conn,
            store,
            campaign_id=campaign_id,
        )
        if existing is None:
            raise
        requested_routes = tuple(
            ForwardPaperRouteRequest(
                route_id=route.route_id,
                playbook_id=route.playbook_id,
            )
            for route in routes
        )
        return _reuse_existing_campaign(
            existing,
            requested_routes=requested_routes,
            expected_baseline_snapshot_hash=(
                preflight.baseline_snapshot_hash
            ),
        )
    return ForwardPaperStartResult(campaign=campaign, routes=routes)


def _start_forward_paper_campaign_for_requests(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    requested_routes: tuple[ForwardPaperRouteRequest, ...],
    started_at_utc: datetime,
    created_at_utc: datetime,
) -> ForwardPaperStartResult:
    """Test/internal primitive for bounded route-contract validation.

    Operator campaign creation must use start_forward_paper_campaign_from_book(),
    which derives the canonical executable universe internally.
    """
    if started_at_utc.tzinfo is None or created_at_utc.tzinfo is None:
        raise ValueError("campaign timestamps must be timezone-aware")
    existing = _load_existing_start_result(
        conn,
        store,
        campaign_id=campaign_id,
    )
    if existing is not None:
        return _reuse_existing_campaign(
            existing,
            requested_routes=requested_routes,
        )
    preflight = preflight_forward_paper_campaign_from_book(
        conn,
        store,
        campaign_id=campaign_id,
        requested_routes=requested_routes,
        as_of_utc=started_at_utc,
    )
    return _persist_forward_paper_campaign_from_preflight(
        conn,
        store,
        campaign_id=campaign_id,
        preflight=preflight,
        started_at_utc=started_at_utc,
        created_at_utc=created_at_utc,
    )


def start_forward_paper_campaign_from_book(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    started_at_utc: datetime,
    created_at_utc: datetime,
) -> ForwardPaperStartResult:
    """Start Campaign #1 only from the full canonical executable universe.

    Caller-supplied route subsets are intentionally not accepted. This enforces the
    C9.1 no-cherry-pick boundary at the operator-facing write path.
    """
    if started_at_utc.tzinfo is None or created_at_utc.tzinfo is None:
        raise ValueError("campaign timestamps must be timezone-aware")

    expected = canonical_forward_paper_route_requests()
    if not expected:
        raise RuntimeError("canonical executable campaign universe is empty")

    existing = _load_existing_start_result(
        conn,
        store,
        campaign_id=campaign_id,
    )
    if existing is not None:
        return _reuse_existing_campaign(
            existing,
            requested_routes=expected,
        )

    preflight = preflight_canonical_forward_paper_campaign_from_book(
        conn,
        store,
        campaign_id=campaign_id,
        as_of_utc=started_at_utc,
    )
    if preflight.requested_route_count != len(expected):
        raise RuntimeError("canonical preflight route-count drift")

    return _persist_forward_paper_campaign_from_preflight(
        conn,
        store,
        campaign_id=campaign_id,
        preflight=preflight,
        started_at_utc=started_at_utc,
        created_at_utc=created_at_utc,
    )
