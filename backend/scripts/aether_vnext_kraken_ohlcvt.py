"""Convert one reviewed Kraken OHLCVT CSV into AETHER research-bar rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aether_vnext.kraken_ohlcvt_history import (
    parse_kraken_ohlcvt_csv,
    research_manifest_bar_rows,
)


def main(
    *,
    csv_file: str,
    asset_id: str,
    interval_minutes: int,
    timestamp_unit: str,
    source_data_version: str,
    source_ref: str,
    output: str,
) -> int:
    raw = Path(csv_file).read_text(encoding="utf-8")
    bars = parse_kraken_ohlcvt_csv(
        raw,
        asset_id=asset_id,
        interval_minutes=interval_minutes,
        timestamp_unit=timestamp_unit,
        source_data_version=source_data_version,
        source_ref=source_ref,
    )
    payload = {
        "asset_id": bars[0].asset_id,
        "interval_seconds": bars[0].interval_minutes * 60,
        "source_id": bars[0].source_id,
        "source_data_version": bars[0].source_data_version,
        "source_ref": bars[0].source_ref,
        "bar_count": len(bars),
        "first_bucket_open_utc": bars[0].bucket_open_utc.isoformat(),
        "last_bucket_close_utc": bars[-1].bucket_close_utc.isoformat(),
        "bars": research_manifest_bar_rows(bars),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-file", required=True)
    parser.add_argument("--asset-id", required=True, choices=("btc", "eth"))
    parser.add_argument("--interval-minutes", required=True, type=int)
    parser.add_argument(
        "--timestamp-unit",
        required=True,
        choices=("unix_seconds", "unix_milliseconds"),
    )
    parser.add_argument("--source-data-version", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(
        main(
            csv_file=args.csv_file,
            asset_id=args.asset_id,
            interval_minutes=args.interval_minutes,
            timestamp_unit=args.timestamp_unit,
            source_data_version=args.source_data_version,
            source_ref=args.source_ref,
            output=args.output,
        )
    )
