"""Read-only probe for Coinbase hourly warm-up versus official Kraken overlap."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median

from aether_vnext.coinbase_prototype_history import fetch_coinbase_hourly_history
from aether_vnext.prototype_history_sources import (
    fetch_kraken_completed_daily,
    fetch_kraken_completed_hourly,
)


UTC = timezone.utc


def _bps(candidate: float, official: float) -> float:
    return abs(float(candidate) - float(official)) / float(official) * 10_000.0


def _overlap_report(candidate, kraken) -> dict[str, object]:
    left = {row.bucket_open_utc: row for row in candidate}
    right = {row.bucket_open_utc: row for row in kraken}
    keys = tuple(sorted(set(left) & set(right)))
    if not keys:
        raise RuntimeError("Coinbase/Kraken probe found no hourly overlap")

    close_diffs = [_bps(left[key].close, right[key].close) for key in keys]
    ohlc_max = [
        max(
            _bps(getattr(left[key], field), getattr(right[key], field))
            for field in ("open", "high", "low", "close")
        )
        for key in keys
    ]
    ordered = sorted(close_diffs)
    p95_index = max(0, min(len(ordered) - 1, int(0.95 * (len(ordered) - 1))))
    return {
        "overlap_count": len(keys),
        "first_overlap_open_utc": keys[0].isoformat(),
        "last_overlap_open_utc": keys[-1].isoformat(),
        "median_close_diff_bps": median(close_diffs),
        "p95_close_diff_bps": ordered[p95_index],
        "max_close_diff_bps": max(close_diffs),
        "max_ohlc_diff_bps": max(ohlc_max),
    }


async def run_probe() -> dict[str, object]:
    as_of = datetime.now(UTC)
    assets: dict[str, object] = {}
    for asset_id in ("btc", "eth"):
        coinbase = await fetch_coinbase_hourly_history(
            asset_id=asset_id,
            end_at_utc=as_of,
            minimum_bars=2200,
        )
        kraken_hourly = await fetch_kraken_completed_hourly(
            asset_id=asset_id,
            end_at_utc=as_of,
        )
        kraken_daily = await fetch_kraken_completed_daily(
            asset_id=asset_id,
            end_at_utc=as_of,
        )
        if len(kraken_hourly) < 600:
            raise RuntimeError(
                f"{asset_id} Kraken hourly overlap too small: {len(kraken_hourly)}"
            )
        if len(kraken_daily) < 50:
            raise RuntimeError(
                f"{asset_id} Kraken daily trend history too small: {len(kraken_daily)}"
            )
        assets[asset_id] = {
            "coinbase_hourly_count": len(coinbase),
            "coinbase_first_open_utc": coinbase[0].bucket_open_utc.isoformat(),
            "coinbase_last_close_utc": coinbase[-1].bucket_close_utc.isoformat(),
            "kraken_hourly_count": len(kraken_hourly),
            "kraken_daily_count": len(kraken_daily),
            "overlap": _overlap_report(coinbase, kraken_hourly),
        }
    return {
        "probe": "aether-vnext-coinbase-warmup-comparison-v1",
        "as_of_utc": as_of.isoformat(),
        "assets": assets,
        "mutation_performed": False,
        "phase18_evidence": False,
        "candidate_source": "coinbase_exchange_public_candles",
        "canonical_execution_market": "kraken",
        "paper_only": True,
        "live_blocked": True,
    }


def main(*, output: str) -> int:
    body = asyncio.run(run_probe())
    rendered = json.dumps(body, indent=2, sort_keys=True)
    Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="aether-vnext-coinbase-warmup-probe.json",
    )
    args = parser.parse_args()
    raise SystemExit(main(output=args.output))
