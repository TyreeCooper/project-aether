"""Export the no-fabrication AETHER vNext runtime-binding review packet.

The packet is intentionally not import-ready. External provider facts and reviewed
freshness policy remain null until the authenticated commissioning pass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aether_vnext.runtime_binding_worklist import runtime_binding_worklist


def binding_review_packet() -> dict[str, object]:
    worklist = runtime_binding_worklist()
    return {
        "packet_type": "aether_vnext_runtime_binding_review",
        "configuration_hash": worklist["configuration_hash"],
        "registry_version": None,
        "ready_for_strict_import": False,
        "expected_asset_ids": worklist["expected_asset_ids"],
        "binding_count": worklist["binding_count"],
        "manifest_template": {
            "registry_version": None,
            "configuration_hash": worklist["configuration_hash"],
            "bindings": worklist["bindings"],
        },
        "asset_review": worklist["assets"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()

    rendered = json.dumps(
        binding_review_packet(),
        indent=2,
        sort_keys=True,
    )
    print(rendered)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
