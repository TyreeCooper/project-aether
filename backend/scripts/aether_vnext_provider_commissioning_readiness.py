"""Print the current provider commissioning worklist as JSON."""
from __future__ import annotations

import json

from aether_vnext.provider_commissioning_readiness import (
    provider_commissioning_readiness,
)


if __name__ == "__main__":
    print(
        json.dumps(
            provider_commissioning_readiness(),
            indent=2,
            sort_keys=True,
        )
    )
