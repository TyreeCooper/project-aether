"""Runtime-mode isolation for the deployed vNext prototype."""
from __future__ import annotations

import os


def configured_vnext_runtime_only() -> bool:
    """Return True only when the explicit prototype-only switch is enabled.

    This switch disables the legacy paper engine loop. It does not weaken any
    vNext PAPER/LIVE safety control and defaults to False everywhere.
    """
    raw = os.getenv("AETHER_VNEXT_RUNTIME_ONLY", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def validate_vnext_runtime_only_environment() -> None:
    if not configured_vnext_runtime_only():
        return
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "burnin":
        raise RuntimeError("vNext runtime-only mode may only run in burnin")
