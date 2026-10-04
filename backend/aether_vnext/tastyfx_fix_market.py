"""tastyfx FIX market-data integration status for AETHER vNext.

tastyfx publicly documents FIX 5.0 SP2 over FIXT 1.1 as its programmatic API, but
the provider-specific specification is supplied only after approval. The public
FIX standard layer lives in fix_market.py; this module intentionally does not guess
private session tags, endpoint values, CompIDs, symbol conventions, or conformance
requirements.

The source ID is reserved so runtime manifests and diagnostics can name the intended
provider without accidentally treating it as operational.
"""
from __future__ import annotations


TASTYFX_FIX_MARKET_SOURCE_ID = "tastyfx_fix_market_data"
TASTYFX_FIX_PROTOCOL = "FIX 5.0 SP2 over FIXT 1.1"
TASTYFX_FIX_IMPLEMENTATION_STATE = "provider_spec_pending"
TASTYFX_FIX_SUPPORTED_ASSETS = frozenset({"eurusd", "usdjpy"})


def tastyfx_fix_public_boundary_blockers() -> tuple[str, ...]:
    """Facts that cannot be closed from tastyfx's public website alone."""
    return (
        "tastyfx_fix_private_spec_required",
        "tastyfx_fix_demo_session_configuration_required",
        "tastyfx_fix_reviewed_symbol_binding_required",
        "tastyfx_fix_conformance_required",
    )
