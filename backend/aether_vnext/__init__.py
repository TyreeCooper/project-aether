"""AETHER vNext replacement runtime boundary.

This package is a greenfield implementation target for the frozen AETHER
specification bundle. Legacy `app.*` runtime imports are deliberately forbidden.

The legacy application remains preserved in Git for rollback/reference only; it
has no design authority over this package.
"""
from __future__ import annotations

RUNTIME_NAMESPACE = "aether_vnext"
SPEC_BUNDLE = "firm-v5.0+playbook-v1.4+precode-v1.0"
PAPER_ONLY = True
LIVE_BLOCKED = True
LEGACY_COMPATIBILITY_REQUIRED = False


def runtime_contract() -> dict[str, object]:
    """Return the immutable Phase-0 replacement-runtime contract."""
    return {
        "runtime_namespace": RUNTIME_NAMESPACE,
        "spec_bundle": SPEC_BUNDLE,
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
        "legacy_compatibility_required": LEGACY_COMPATIBILITY_REQUIRED,
    }
