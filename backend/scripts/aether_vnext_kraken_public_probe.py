"""Credential-free Kraken BTC/ETH public market probe for AETHER vNext.

This probe is intentionally outside canonical Campaign #1 and outside the vNext
database. It proves that the public Kraken market-data path can supply current
BTC/ETH BBO and matched-trade observations while the remaining provider bindings
are still uncommissioned.

It never authenticates, never opens the database, never creates orders, and never
claims Phase-18/P11 evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from aether_vnext.kraken_public import (
    fetch_kraken_public_tickers,
    fetch_kraken_public_trades,
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
            "AETHER Kraken public probe supports only btc,eth: "
            + ",".join(unsupported)
        )
    return values


def _serialize(tickers, trades) -> dict[str, object]:
    return {
        "provider": "Kraken",
        "scope": "btc_eth_commissioning_only",
        "canonical_campaign_1": False,
        "phase18_evidence": False,
        "database_mutation": False,
        "authentication_required": False,
        "live_execution_authorized": False,
        "paper_only": True,
        "live_blocked": True,
        "ticker": {
            "endpoint": tickers.endpoint,
            "status_system": tickers.status_system,
            "status_api_version": tickers.status_api_version,
            "connection_id": tickers.connection_id,
            "subscription_acknowledged": tickers.subscription_acknowledged,
            "requested_symbols": list(tickers.requested_symbols),
            "quotes": [
                {
                    "asset_id": row.asset_id,
                    "source_id": row.source_id,
                    "venue": row.venue,
                    "bid": row.bid,
                    "ask": row.ask,
                    "last": row.last,
                    "mark": row.mark,
                    "exchange_ts": (
                        None
                        if row.exchange_ts is None
                        else row.exchange_ts.isoformat()
                    ),
                    "received_ts": row.received_ts.isoformat(),
                    "adapter_version": row.adapter_version,
                }
                for row in tickers.quotes
            ],
        },
        "trade": {
            "endpoint": trades.endpoint,
            "status_system": trades.status_system,
            "status_api_version": trades.status_api_version,
            "connection_id": trades.connection_id,
            "subscription_acknowledged": trades.subscription_acknowledged,
            "requested_symbols": list(trades.requested_symbols),
            "prints": [
                {
                    "asset_id": row.asset_id,
                    "source_id": row.source_id,
                    "price": row.price,
                    "volume": row.volume,
                    "exchange_ts": row.exchange_ts.isoformat(),
                    "received_ts": row.received_ts.isoformat(),
                }
                for row in trades.prints
            ],
        },
    }


async def _main(
    *,
    assets: tuple[str, ...],
    ticker_timeout_s: float,
    trade_timeout_s: float,
    output: str | None,
) -> int:
    tickers = await fetch_kraken_public_tickers(
        assets=assets,
        timeout_s=ticker_timeout_s,
    )
    trades = await fetch_kraken_public_trades(
        assets=assets,
        timeout_s=trade_timeout_s,
    )
    payload = _serialize(tickers, trades)
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
    parser.add_argument("--ticker-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--trade-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                assets=_assets(args.assets),
                ticker_timeout_s=args.ticker_timeout_seconds,
                trade_timeout_s=args.trade_timeout_seconds,
                output=args.output,
            )
        )
    )
