"""Credential-free Kraken BTC/ETH freshness evidence probe.

Repeatedly samples the public Kraken v2 ticker feed and measures observed provider
timestamp cadence plus provider-to-receive latency. It deliberately does not choose
or write stale_threshold_ms, does not authenticate, and does not touch the vNext DB.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

from aether_vnext.kraken_public import KrakenTickerBatch, fetch_kraken_public_tickers
from aether_vnext.provider_freshness import (
    ProviderTimingSample,
    measure_provider_timing,
    provider_timing_evidence_payload,
)


_ALLOWED_ASSETS = frozenset({"btc", "eth"})


def _assets(raw: str) -> tuple[str, ...]:
    values = tuple(
        value.strip().lower()
        for value in str(raw).split(",")
        if value.strip()
    )
    if not values:
        raise ValueError("at least one Kraken asset is required")
    if len(values) != len(set(values)):
        raise ValueError("duplicate Kraken asset")
    unsupported = tuple(value for value in values if value not in _ALLOWED_ASSETS)
    if unsupported:
        raise ValueError(
            "AETHER Kraken freshness probe supports only btc,eth: "
            + ",".join(unsupported)
        )
    return values


async def collect_kraken_freshness_evidence(
    *,
    assets: tuple[str, ...],
    rounds: int,
    timeout_s: float,
    pause_s: float,
    fetcher: Callable[..., Awaitable[KrakenTickerBatch]] = fetch_kraken_public_tickers,
) -> dict[str, object]:
    if isinstance(rounds, bool) or rounds < 2:
        raise ValueError("rounds must be an integer >= 2")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if pause_s < 0:
        raise ValueError("pause_s cannot be negative")

    samples: dict[str, list[ProviderTimingSample]] = {
        asset_id: [] for asset_id in assets
    }
    statuses: list[str] = []

    for index in range(rounds):
        batch = await fetcher(
            assets=assets,
            timeout_s=timeout_s,
        )
        statuses.append(batch.status_system)
        by_asset = {quote.asset_id: quote for quote in batch.quotes}
        missing = tuple(asset for asset in assets if asset not in by_asset)
        if missing:
            raise RuntimeError(
                "Kraken freshness sample missing asset(s): " + ",".join(missing)
            )

        for asset_id in assets:
            quote = by_asset[asset_id]
            if quote.exchange_ts is None:
                raise RuntimeError(
                    f"Kraken freshness sample lacks provider timestamp: {asset_id}"
                )
            samples[asset_id].append(
                ProviderTimingSample(
                    provider_ts_utc=quote.exchange_ts,
                    received_ts_utc=quote.received_ts,
                )
            )

        if index + 1 < rounds and pause_s:
            await asyncio.sleep(pause_s)

    if any(status != "online" for status in statuses):
        raise RuntimeError("Kraken freshness probe observed non-online provider status")

    evidence = {
        asset_id: provider_timing_evidence_payload(
            measure_provider_timing(tuple(rows))
        )
        for asset_id, rows in samples.items()
    }
    return {
        "provider": "Kraken",
        "scope": "btc_eth_commissioning_only",
        "sample_rounds": rounds,
        "database_mutation": False,
        "authentication_required": False,
        "policy_selected": False,
        "stale_threshold_ms": None,
        "paper_only": True,
        "live_blocked": True,
        "assets": evidence,
    }


async def _main(
    *,
    assets: tuple[str, ...],
    rounds: int,
    timeout_s: float,
    pause_s: float,
    output: str | None,
) -> int:
    payload = await collect_kraken_freshness_evidence(
        assets=assets,
        rounds=rounds,
        timeout_s=timeout_s,
        pause_s=pause_s,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", default="btc,eth")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                assets=_assets(args.assets),
                rounds=args.rounds,
                timeout_s=args.timeout_seconds,
                pause_s=args.pause_seconds,
                output=args.output,
            )
        )
    )
