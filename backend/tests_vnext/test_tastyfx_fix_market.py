from __future__ import annotations

from aether_vnext.tastyfx_fix_market import (
    TASTYFX_FIX_IMPLEMENTATION_STATE,
    TASTYFX_FIX_MARKET_SOURCE_ID,
    TASTYFX_FIX_PROTOCOL,
    TASTYFX_FIX_SUPPORTED_ASSETS,
    tastyfx_fix_public_boundary_blockers,
)


def test_tastyfx_fix_contract_is_explicitly_provider_spec_pending() -> None:
    assert TASTYFX_FIX_MARKET_SOURCE_ID == "tastyfx_fix_market_data"
    assert TASTYFX_FIX_PROTOCOL == "FIX 5.0 SP2 over FIXT 1.1"
    assert TASTYFX_FIX_IMPLEMENTATION_STATE == "provider_spec_pending"
    assert TASTYFX_FIX_SUPPORTED_ASSETS == frozenset({"eurusd", "usdjpy"})
    assert tastyfx_fix_public_boundary_blockers() == (
        "tastyfx_fix_private_spec_required",
        "tastyfx_fix_demo_session_configuration_required",
        "tastyfx_fix_reviewed_symbol_binding_required",
        "tastyfx_fix_conformance_required",
    )
