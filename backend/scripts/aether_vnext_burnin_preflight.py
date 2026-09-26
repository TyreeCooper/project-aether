"""Read-only CLI for AETHER vNext forward-paper burn-in preflight."""
from __future__ import annotations

import argparse
import asyncio
import json

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.forward_paper_preflight import (
    ForwardPaperRouteRequest,
    preflight_forward_paper_campaign_from_book,
)
from aether_vnext.store import VNextStore


def _parse_routes(raw: str) -> tuple[ForwardPaperRouteRequest, ...]:
    payload = json.loads(raw)
    if not isinstance(payload, list) or not payload:
        raise ValueError("routes JSON must be a non-empty list")
    out: list[ForwardPaperRouteRequest] = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("each route entry must be an object")
        out.append(
            ForwardPaperRouteRequest(
                route_id=str(row.get("route_id") or ""),
                playbook_id=str(row.get("playbook_id") or ""),
            )
        )
    return tuple(out)


def _serialize(result) -> dict[str, object]:
    return {
        "campaign_id": result.campaign_id,
        "configuration_hash": result.configuration_hash,
        "policy_version": result.policy_version,
        "requested_route_count": result.requested_route_count,
        "startable": result.startable,
        "baseline_snapshot_hash": result.baseline_snapshot_hash,
        "blockers": list(result.blockers),
        "missing_routes": list(result.missing_routes),
        "routes": [
            {
                "route_id": row.request.route_id,
                "playbook_id": row.request.playbook_id,
                "eligible": row.eligible,
                "playbook_version": row.playbook_version,
                "held_out_window_ids": list(row.held_out_window_ids),
                "held_out_window_count": row.held_out_window_count,
                "independent_held_out_n": row.independent_held_out_n,
                "route_baseline_hash": row.route_baseline_hash,
                "campaign_route_id": row.campaign_route_id,
                "blockers": list(row.blockers),
            }
            for row in result.route_results
        ],
    }


async def _main(campaign_id: str, routes_json: str) -> int:
    routes = _parse_routes(routes_json)
    store = VNextStore(schema="aether_vnext")
    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            result = await connection.run_sync(
                lambda sync_conn: preflight_forward_paper_campaign_from_book(
                    sync_conn,
                    store,
                    campaign_id=campaign_id,
                    requested_routes=routes,
                )
            )
    print(json.dumps(_serialize(result), indent=2, sort_keys=True))
    return 0 if result.startable else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--routes-json", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.campaign_id, args.routes_json)))
