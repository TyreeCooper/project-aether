from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from aether_vnext.registry_runtime import RuntimeRegistryBinding


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_tradinghours_calendar_probe.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_tradinghours_calendar_probe_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(
    *,
    asset_id: str,
    market_id: str | None,
) -> dict:
    return {
        "binding": RuntimeRegistryBinding(
            asset_id=asset_id,
            broker_symbol="TEST",
            primary_market_source_id="reviewed.source",
            stale_threshold_ms=1500,
            calendar_provider_id="tradinghours_v3",
            calendar_market_id=market_id,
            shortability_provider_id=(
                "reviewed.locate"
                if asset_id in {"nvda", "tsla", "pltr"}
                else None
            ),
        )
    }


def test_calendar_map_uses_durable_runtime_binding_identity() -> None:
    module = _module()
    mapping = module._calendar_map(
        (
            _row(asset_id="nvda", market_id="US.NYSE"),
            _row(asset_id="tsla", market_id="US.NYSE"),
        )
    )
    assert mapping == {"us_rth": "US.NYSE"}


def test_calendar_map_rejects_conflicting_market_identity() -> None:
    module = _module()
    with pytest.raises(ValueError, match="conflicting TradingHours market IDs"):
        module._calendar_map(
            (
                _row(asset_id="nvda", market_id="US.NYSE"),
                _row(asset_id="tsla", market_id="US.NASDAQ"),
            )
        )


def test_calendar_map_rejects_missing_market_identity() -> None:
    module = _module()
    with pytest.raises(ValueError, match="calendar_market_id missing"):
        module._calendar_map(
            (_row(asset_id="nvda", market_id=None),)
        )


def test_probe_requires_external_token_and_never_embeds_one() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "AETHER_VNEXT_TRADINGHOURS_API_TOKEN" in source
    assert "Bearer " not in source
