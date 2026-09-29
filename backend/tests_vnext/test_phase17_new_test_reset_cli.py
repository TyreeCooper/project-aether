from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "aether_vnext_new_test_reset.py"
    )
    spec = importlib.util.spec_from_file_location("new_test_reset_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_payload_is_explicitly_non_mutating() -> None:
    module = _load_script()
    payload = module.preview_payload(
        {
            "resettable": True,
            "blockers": (),
            "seed_sleeves": {
                "kraken_paper": 4000.0,
                "tastyfx_paper": 2000.0,
                "ninja_paper": 2000.0,
                "ibkr_paper": 2000.0,
            },
            "seed_bank_total_usd": 10000.0,
            "prior_state_hash": "abc",
            "prior_state": {"closed_trade_count": 17},
        }
    )

    assert payload["mode"] == "preview"
    assert payload["mutation_performed"] is False
    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True
    assert payload["seed_bank_total_usd"] == 10000.0
    assert payload["prior_state"]["closed_trade_count"] == 17


def test_execute_requires_exact_confirmation_token() -> None:
    module = _load_script()

    with pytest.raises(ValueError, match="RESET-VNEXT-PAPER-TEST"):
        module.require_execute_confirmation(
            execute=True,
            confirm=None,
        )
    with pytest.raises(ValueError, match="RESET-VNEXT-PAPER-TEST"):
        module.require_execute_confirmation(
            execute=True,
            confirm="reset",
        )

    module.require_execute_confirmation(
        execute=True,
        confirm=module.CONFIRM_TOKEN,
    )


def test_preview_requires_no_confirmation() -> None:
    module = _load_script()
    module.require_execute_confirmation(
        execute=False,
        confirm=None,
    )


def test_reset_script_uses_isolated_vnext_runtime_and_not_legacy_app() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "aether_vnext_new_test_reset.py"
    )
    source = path.read_text(encoding="utf-8")

    assert "open_vnext_engine" in source
    assert "start_new_paper_test_epoch" in source
    assert "RESET-VNEXT-PAPER-TEST" in source
    assert "from app" not in source
    assert "import app" not in source
