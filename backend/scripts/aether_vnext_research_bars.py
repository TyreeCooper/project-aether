"""Import one reviewed real PIT research-bar dataset into AETHER vNext."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.research_warehouse import (
    parse_research_bar_manifest,
    persist_research_bar_manifest,
)
from aether_vnext.store import VNextStore


def _load_payload(
    *,
    manifest_json: str | None,
    manifest_file: str | None,
) -> dict:
    if (manifest_json is None) == (manifest_file is None):
        raise ValueError(
            "choose exactly one of --manifest-json or --manifest-file"
        )
    raw = (
        manifest_json
        if manifest_json is not None
        else Path(str(manifest_file)).read_text(encoding="utf-8")
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return payload


async def _main(
    *,
    manifest_json: str | None,
    manifest_file: str | None,
    output: str | None,
) -> int:
    payload = _load_payload(
        manifest_json=manifest_json,
        manifest_file=manifest_file,
    )
    manifest = parse_research_bar_manifest(payload)
    store = VNextStore(schema="aether_vnext")
    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            report = await connection.run_sync(
                lambda sync_conn: persist_research_bar_manifest(
                    sync_conn,
                    store,
                    manifest,
                )
            )

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest-json")
    source.add_argument("--manifest-file")
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                manifest_json=args.manifest_json,
                manifest_file=args.manifest_file,
                output=args.output,
            )
        )
    )
