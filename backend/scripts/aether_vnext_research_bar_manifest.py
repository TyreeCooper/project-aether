"""Build one canonical immutable research-bar manifest without database I/O.

Input JSON contains:
- source_ref;
- dataset_spec metadata;
- reviewed normalized bar_rows with explicit bucket/availability timestamps.

The command computes content-addressed identity through the existing assembler and
emits a manifest accepted directly by aether_vnext_research_bars.py.

It never downloads data, infers provider semantics, opens the database, or persists
research.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Mapping

from aether_vnext.research_bar_manifest_assembly import (
    ResearchDatasetSpec,
    assemble_research_bar_manifest,
)
from aether_vnext.research_warehouse import (
    parse_research_bar_manifest,
)


def _load_payload(
    *,
    input_json: str | None,
    input_file: str | None,
) -> dict[str, object]:
    if (input_json is None) == (input_file is None):
        raise ValueError(
            "choose exactly one of --input-json or --input-file"
        )
    raw = (
        input_json
        if input_json is not None
        else Path(str(input_file)).read_text(encoding="utf-8")
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    return payload


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _asset_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("asset_ids must be a non-empty list")
    rows = tuple(_text(item, "asset_ids") for item in value)
    if any(item != item.lower() for item in rows):
        raise ValueError("asset_ids must contain canonical lowercase IDs")
    if len(rows) != len(set(rows)):
        raise ValueError("asset_ids cannot contain duplicates")
    return rows


def _dataset_spec(payload: object) -> ResearchDatasetSpec:
    if not isinstance(payload, Mapping):
        raise ValueError("dataset_spec must be a JSON object")
    return ResearchDatasetSpec(
        dataset_snapshot_id=_text(
            payload.get("dataset_snapshot_id"),
            "dataset_snapshot_id",
        ),
        created_at_utc=_utc(
            payload.get("created_at_utc"),
            "created_at_utc",
        ),
        as_of_utc=_utc(payload.get("as_of_utc"), "as_of_utc"),
        start_at_utc=_utc(
            payload.get("start_at_utc"),
            "start_at_utc",
        ),
        end_at_utc=_utc(
            payload.get("end_at_utc"),
            "end_at_utc",
        ),
        asset_ids=_asset_ids(payload.get("asset_ids")),
        data_version=_text(
            payload.get("data_version"),
            "data_version",
        ),
        source_registry_version=_text(
            payload.get("source_registry_version"),
            "source_registry_version",
        ),
        product_registry_version=_text(
            payload.get("product_registry_version"),
            "product_registry_version",
        ),
        calendar_version=_text(
            payload.get("calendar_version"),
            "calendar_version",
        ),
        missing_data_policy=_text(
            payload.get("missing_data_policy"),
            "missing_data_policy",
        ),
    )


def _bar_rows(payload: object) -> tuple[dict[str, object], ...]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("bar_rows must be a non-empty list")
    out: list[dict[str, object]] = []
    for row in payload:
        if not isinstance(row, Mapping):
            raise ValueError("bar_rows entries must be JSON objects")
        normalized = dict(row)
        for field in (
            "bucket_open_utc",
            "bucket_close_utc",
            "available_at_utc",
        ):
            normalized[field] = _utc(row.get(field), field)
        out.append(normalized)
    return tuple(out)


def _manifest_payload(payload: Mapping[str, object]) -> dict[str, object]:
    source_ref = _text(payload.get("source_ref"), "source_ref")
    assembly = assemble_research_bar_manifest(
        source_ref=source_ref,
        dataset_spec=_dataset_spec(payload.get("dataset_spec")),
        bar_rows=_bar_rows(payload.get("bar_rows")),
    )
    manifest = assembly.manifest
    snapshot = manifest.snapshot
    result: dict[str, object] = {
        "manifest_version": manifest.manifest_version,
        "source_ref": manifest.source_ref,
        "snapshot": {
            "dataset_snapshot_id": snapshot.dataset_snapshot_id,
            "created_at_utc": snapshot.created_at_utc.isoformat(),
            "as_of_utc": snapshot.as_of_utc.isoformat(),
            "start_at_utc": snapshot.start_at_utc.isoformat(),
            "end_at_utc": snapshot.end_at_utc.isoformat(),
            "asset_ids": list(snapshot.asset_ids),
            "data_version": snapshot.data_version,
            "source_registry_version": snapshot.source_registry_version,
            "product_registry_version": snapshot.product_registry_version,
            "calendar_version": snapshot.calendar_version,
            "pit": snapshot.pit,
            "missing_data_policy": snapshot.missing_data_policy,
            "content_hash": snapshot.content_hash,
        },
        "bars": [
            {
                "asset_id": row.asset_id,
                "interval_seconds": row.interval_seconds,
                "bucket_open_utc": row.bucket_open_utc.isoformat(),
                "bucket_close_utc": row.bucket_close_utc.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "source_id": row.source_id,
                "source_data_version": row.source_data_version,
                "source_ref": row.source_ref,
                "available_at_utc": row.available_at_utc.isoformat(),
            }
            for row in manifest.bars
        ],
    }
    # Prove the emitted representation round-trips through the canonical parser.
    parse_research_bar_manifest(result)
    return result


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


def main(
    *,
    input_json: str | None,
    input_file: str | None,
    output: str | None = None,
) -> int:
    payload = _load_payload(
        input_json=input_json,
        input_file=input_file,
    )
    manifest = _manifest_payload(payload)
    _emit(manifest, output)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-json")
    source.add_argument("--input-file")
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        main(
            input_json=args.input_json,
            input_file=args.input_file,
            output=args.output,
        )
    )
