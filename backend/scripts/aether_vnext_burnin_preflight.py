"""Read-only canonical CLI for AETHER vNext forward-paper burn-in preflight."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.forward_paper_preflight import (
    canonical_forward_paper_manifest,
    preflight_canonical_forward_paper_campaign_from_book,
)
from aether_vnext.store import VNextStore


def _serialize(result) -> dict[str, object]:
    manifest = canonical_forward_paper_manifest()
    return {
        "campaign_id": result.campaign_id,
        "configuration_hash": result.configuration_hash,
        "policy_version": result.policy_version,
        "canonical_coverage_route_count": manifest.coverage_route_count,
        "canonical_executable_route_count": manifest.executable_route_count,
        "canonical_excluded_route_count": manifest.excluded_route_count,
        "canonical_exclusions": [
            {
                "route_id": row.request.route_id,
                "playbook_id": row.request.playbook_id,
                "reason": row.reason,
            }
            for row in manifest.exclusions
        ],
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
                "runtime_registry_binding_hash": (
                    row.runtime_registry_binding_hash
                ),
                "route_baseline_hash": row.route_baseline_hash,
                "campaign_route_id": row.campaign_route_id,
                "blockers": list(row.blockers),
            }
            for row in result.route_results
        ],
    }


def _emit_report(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(campaign_id: str, output: str | None) -> int:
    store = VNextStore(schema="aether_vnext")
    as_of_utc = datetime.now(timezone.utc)
    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            result = await connection.run_sync(
                lambda sync_conn: preflight_canonical_forward_paper_campaign_from_book(
                    sync_conn,
                    store,
                    campaign_id=campaign_id,
                    as_of_utc=as_of_utc,
                )
            )
    payload = _serialize(result)
    _emit_report(payload, output)
    return 0 if result.startable else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.campaign_id, args.output)))
