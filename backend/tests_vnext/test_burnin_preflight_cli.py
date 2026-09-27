from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_burnin_preflight.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_burnin_preflight_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_report_writer_persists_exact_json(tmp_path: Path) -> None:
    module = _module()
    payload = {
        "campaign_id": "burnin-001",
        "startable": False,
        "blockers": ["missing_current_held_out_baseline"],
    }
    output = tmp_path / "preflight.json"

    module._emit_report(payload, str(output))

    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_operator_preflight_is_canonical_only() -> None:
    module = _module()
    source = SCRIPT.read_text(encoding="utf-8")
    assert not hasattr(module, "_parse_routes")
    assert "--routes-json" not in source
    assert "preflight_canonical_forward_paper_campaign_from_book" in source
    assert "canonical_forward_paper_manifest" in source
