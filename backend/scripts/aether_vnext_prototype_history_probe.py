"""Probe real BTC/ETH historical warm-up sources without database mutation."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median

from aether_vnext.prototype_history_sources import (
    fetch_cryptocompare_kraken_hourly,
    fetch_kraken_completed_daily,
    fetch_kraken_completed_hourly,
)


UTC = timezone.utc


def _bps(candidate: float, official: float) -> float:
    return abs(float(candidate) - float(official)) / float(official) * 10_000.0


def _overlap_report(candidate, official) -> dict[str, object]:
    left = {row.bucket_open_utc: row for row in candidate}
    right = {row.bucket_open_utc: row for row in official}
    keys = tuple(sorted(set(left) & set(right)))
    if not keys:
        raise RuntimeError("historical probe found no Kraken hourly overlap")

    close_diffs = [_bps(left[key].close, right[key].close) for key in keys]
    ohlc_diffs = [
        max(
            _bps(getattr(left[key], field), getattr(right[key], field))
            for field in ("open", "high", "low", "close")
        )
        for key in keys
    ]
    ordered_close = sorted(close_diffs)
    p95_index = max(0, min(len(ordered_close) - 1, int(0.95 * (len(ordered_close) - 1))))
    return {
        "overlap_count": len(keys),
        "first_overlap_open_utc": keys[0].isoformat(),
        "last_overlap_open_utc": keys[-1].isoformat(),
        "median_close_diff_bps": median(close_diffs),
        "p95_close_diff_bps": ordered_close[p95_index],
        "max_close_diff_bps": max(close_diffs),
        "max_ohlc_diff_bps": max(ohlc_diffs),
    }


async def run_probe() -> dict[str, object]:
    as_of = datetime.now(UTC)
    assets: dict[str, object] = {}

    for asset_id in ("btc", "eth"):
        warmup = await fetch_cryptocompare_kraken_hourly(
            asset_id=asset_id,
            end_at_utc=as_of,
            minimum_bars=2200,
        )
        official_hourly = await fetch_kraken_completed_hourly(
            asset_id=asset_id,
            end_at_utc=as_of,
        )
        official_daily = await fetch_kraken_completed_daily(
            asset_id=asset_id,
            end_at_utc=as_of,
        )
        if len(official_hourly) < 600:
            raise RuntimeError(
                f"{asset_id} Kraken REST returned only {len(official_hourly)} completed hourly bars"
            )
        if len(official_daily) < 50:
            raise RuntimeError(
                f"{asset_id} Kraken REST returned only {len(official_daily)} completed daily bars"
            )

        assets[asset_id] = {
            "warmup_hourly_count": len(warmup),
            "warmup_first_open_utc": warmup[0].bucket_open_utc.isoformat(),
            "warmup_last_close_utc": warmup[-1].bucket_close_utc.isoformat(),
            "kraken_hourly_count": len(official_hourly),
            "kraken_daily_count": len(official_daily),
            "kraken_daily_last_close_utc": official_daily[-1].bucket_close_utc.isoformat(),
            "overlap": _overlap_report(warmup, official_hourly),
        }

    return {
        "probe": "aether-vnext-prototype-history-warmup-v1",
        "as_of_utc": as_of.isoformat(),
        "assets": assets,
        "mutation_performed": False,
        "phase18_evidence": False,
        "paper_only": True,
        "live_blocked": True,
    }


def main(*, output: str) -> int:
    payload = asyncio.run(run_probe())
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="aether-vnext-prototype-history-probe.json",
    )
    args = parser.parse_args()
    raise SystemExit(main(output=args.output))
