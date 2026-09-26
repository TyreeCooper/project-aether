"""Start a C9.1 forward-paper burn-in campaign from the vNext book.

The write path consumes the same read-only preflight result exposed to operators so
inspection and persistence cannot silently disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.engine import Connection

from aether_vnext.forward_paper import ForwardPaperCampaign, ForwardPaperRouteBaseline
from aether_vnext.forward_paper_preflight import (
    ForwardPaperRouteRequest,
    preflight_forward_paper_campaign_from_book,
    route_baselines_from_preflight,
)
from aether_vnext.store import VNextStore


@dataclass(frozen=True, slots=True)
class ForwardPaperStartResult:
    campaign: ForwardPaperCampaign
    routes: tuple[ForwardPaperRouteBaseline, ...]

    @property
    def baseline_snapshot_hash(self) -> str:
        return self.campaign.baseline_snapshot_hash


def start_forward_paper_campaign_from_book(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    requested_routes: tuple[ForwardPaperRouteRequest, ...],
    started_at_utc: datetime,
    created_at_utc: datetime,
) -> ForwardPaperStartResult:
    """Preflight then atomically persist one forward-paper campaign."""
    if started_at_utc.tzinfo is None or created_at_utc.tzinfo is None:
        raise ValueError("campaign timestamps must be timezone-aware")

    preflight = preflight_forward_paper_campaign_from_book(
        conn,
        store,
        campaign_id=campaign_id,
        requested_routes=requested_routes,
    )
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
    store.record_forward_paper_campaign(
        conn,
        campaign,
        routes=routes,
    )
    return ForwardPaperStartResult(campaign=campaign, routes=routes)
