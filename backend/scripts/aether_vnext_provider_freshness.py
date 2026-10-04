"""Measure provider freshness evidence from recorded timestamp samples.

Input JSON must be a list of objects with provider_ts_utc and received_ts_utc.
This tool emits measurements only; it never chooses stale_threshold_ms.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from aether_vnext.provider_freshness import (
    ProviderTimingSample,
    measure_provider_timing,
    provider_timing_evidence_payload,
)


def _parse_timestamp(value: object, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _load_samples(path: Path) -> tuple[ProviderTimingSample, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("input JSON must be a list")
    rows: list[ProviderTimingSample] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"sample {index} must be an object")
        rows.append(
            ProviderTimingSample(
                provider_ts_utc=_parse_timestamp(
                    row.get("provider_ts_utc"),
                    field=f"sample {index} provider_ts_utc",
                ),
                received_ts_utc=_parse_timestamp(
                    row.get("received_ts_utc"),
                    field=f"sample {index} received_ts_utc",
                ),
            )
        )
    return tuple(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json")
    parser.add_argument("--output")
    args = parser.parse_args()

    evidence = measure_provider_timing(
        _load_samples(Path(args.input_json))
    )
    rendered = json.dumps(
        provider_timing_evidence_payload(evidence),
        indent=2,
        sort_keys=True,
    )
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
