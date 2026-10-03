"""Enumerate reviewed TradingHours market candidates without binding them."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from aether_vnext.tradinghours_discovery import fetch_allowed_tradinghours_markets


def _serialize(rows) -> dict[str, object]:
    return {
        "provider": "TradingHours",
        "binding_performed": False,
        "candidate_count": len(rows),
        "candidates": [
            {
                "fin_id": row.fin_id,
                "exchange": row.exchange,
                "market": row.market,
                "products": row.products,
                "mic": row.mic,
                "asset_type": row.asset_type,
                "group": row.group,
            }
            for row in rows
        ],
    }


async def _main(*, output: str | None) -> int:
    token = os.getenv("AETHER_VNEXT_TRADINGHOURS_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AETHER_VNEXT_TRADINGHOURS_API_TOKEN is required")
    rows = await fetch_allowed_tradinghours_markets(api_token=token)
    payload = _serialize(rows)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(output=args.output)))
