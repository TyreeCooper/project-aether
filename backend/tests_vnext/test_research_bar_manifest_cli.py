from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aether_vnext.research_warehouse import (
    parse_research_bar_manifest,
)


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "aether_vnext_research_bar_manifest.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "aether_vnext_research_bar_manifest_script",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, object]:
    return {
        "source_ref": "reviewed-dataset-source",
        "dataset_spec": {
            "dataset_snapshot_id": "dataset-cli-v1",
            "created_at_utc": "2026-01-03T00:00:00+00:00",
            "as_of_utc": "2026-01-03T00:00:00+00:00",
            "start_at_utc": "2026-01-01T00:00:00+00:00",
            "end_at_utc": "2026-01-02T23:59:59+00:00",
            "asset_ids": ["btc"],
            "data_version": "reviewed-bars-v1",
            "source_registry_version": "sources-v1",
            "product_registry_version": "products-v1",
            "calendar_version": "calendar-v1",
            "missing_data_policy": "fail_closed",
        },
        "bar_rows": [
            {
                "asset_id": "btc",
                "interval_seconds": 3600,
                "bucket_open_utc": "2026-01-01T00:00:00+00:00",
                "bucket_close_utc": "2026-01-01T01:00:00+00:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
                "source_id": "reviewed-provider",
                "source_data_version": "history-v1",
                "source_ref": "reviewed-provider:bar-1",
                "available_at_utc": "2026-01-01T01:00:00+00:00",
            }
        ],
    }


def test_manifest_payload_round_trips_through_canonical_parser() -> None:
    module = _module()
    payload = module._manifest_payload(_payload())

    manifest = parse_research_bar_manifest(payload)
    assert manifest.snapshot.dataset_snapshot_id == "dataset-cli-v1"
    assert len(manifest.snapshot.content_hash) == 64
    assert manifest.snapshot.content_hash != "0" * 64
    assert len(manifest.bars) == 1
    assert manifest.bars[0].asset_id == "btc"


def test_main_writes_directly_importable_manifest(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "research-bars.json"

    code = module.main(
        input_json=json.dumps(_payload()),
        input_file=None,
        output=str(output),
    )

    assert code == 0
    rendered = json.loads(output.read_text(encoding="utf-8"))
    manifest = parse_research_bar_manifest(rendered)
    assert manifest.snapshot.content_hash == rendered["snapshot"]["content_hash"]


def test_manifest_builder_rejects_naive_timestamps() -> None:
    module = _module()
    payload = _payload()
    payload["bar_rows"][0]["available_at_utc"] = "2026-01-01T01:00:00"

    with pytest.raises(ValueError, match="timezone-aware"):
        module._manifest_payload(payload)


def test_manifest_builder_is_read_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "open_vnext_engine" not in source
    assert "VNextStore" not in source
    assert "persist_research_bar_manifest" not in source
    assert "requests." not in source
    assert "httpx." not in source
