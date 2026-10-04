"""Runtime isolation for the deployed vNext sandbox."""
from __future__ import annotations

import os


def configured_vnext_runtime_only() -> bool:
    """Sandbox is always vNext-only; legacy trading loops are never started."""
    return os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "sandbox"


def validate_vnext_runtime_only_environment() -> None:
    environment = os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower()
    if environment and environment != "sandbox":
        raise RuntimeError("vNext sandbox runtime requires AETHER_VNEXT_ENVIRONMENT=sandbox")
