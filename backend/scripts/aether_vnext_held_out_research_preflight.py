"""Read-only preflight for the canonical vNext HELD_OUT research runner."""
from __future__ import annotations

import json

from aether_vnext.held_out_research_runner import (
    preflight_canonical_held_out_research_runner,
)


def main() -> int:
    result = preflight_canonical_held_out_research_runner()
    print(
        json.dumps(
            {
                "startable": result.startable,
                "route_count": result.route_count,
                "required_indicators": list(result.required_indicators),
                "blockers": list(result.blockers),
                "routes": [
                    {
                        "route_id": row.route_id,
                        "playbook_id": row.playbook_id,
                        "playbook_version": row.playbook_version,
                        "mechanism_class": row.mechanism_class,
                    }
                    for row in result.routes
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.startable else 2


if __name__ == "__main__":
    raise SystemExit(main())
