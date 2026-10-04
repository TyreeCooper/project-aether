"""Bootstrap the canonical frozen policy identity in an empty vNext book."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.policy_bootstrap import bootstrap_canonical_policy_snapshot
from aether_vnext.store import VNextStore


async def _main() -> None:
    now = datetime.now(timezone.utc)
    store = VNextStore(schema="aether_vnext")
    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            inserted = await connection.run_sync(
                lambda sync_conn: bootstrap_canonical_policy_snapshot(
                    sync_conn,
                    store,
                    effective_at_utc=now,
                    created_at_utc=now,
                )
            )
    print("canonical_policy_snapshot=" + ("inserted" if inserted else "present"))


if __name__ == "__main__":
    asyncio.run(_main())
