from __future__ import annotations

import pytest

from scripts.aether_vnext_prototype_history_bootstrap import CONFIRMATION


def test_bootstrap_confirmation_token_is_explicit_and_stable() -> None:
    assert CONFIRMATION == "BOOTSTRAP-VNEXT-PROTOTYPE-HISTORY"


def test_bootstrap_is_never_phase18_evidence_by_contract() -> None:
    import inspect
    import scripts.aether_vnext_prototype_history_bootstrap as module

    source = inspect.getsource(module)
    assert '"phase18_evidence": False' in source
    assert "prototype_market_bars" in source
    assert "research_bars" not in source
