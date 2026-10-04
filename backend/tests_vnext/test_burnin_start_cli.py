from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_burnin_start.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_burnin_start_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_campaign_start_operator_path_is_canonical_and_subset_free() -> None:
    module = _module()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--routes-json" not in source
    assert "start_forward_paper_campaign_from_book" in source
    assert "requested_routes" not in source
    assert hasattr(module, "_serialize")
    assert hasattr(module, "_emit_report")
