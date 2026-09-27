"""One-shot Kraken public WebSocket v2 probe into canonical vNext market ingress.

The probe is public market data only. It never authenticates to Kraken and never
submits orders. Database writes are limited to MarketObservation and
market_ingress_attempt audit rows through the vNext Firm boundary.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.kraken_public import fetch_kraken_public_tickers
from aether_vnext.market_ingress import ingest_market_quotes
from aether_vnext.store import VNextStore


def _serialize_batch(batch, ingress_results) -> dict[str, object]:
    by_asset = {row.asset_id: row for row in ingress_results}
    return {
        "provider": "Kraken",
        "transport": "public_websocket_v2",
        "endpoint": batch.endpoint,
        "status_system": batch.status_system,
        "status_api_version": batch.status_api_version,
        "connection_id": batch.connection_id,
        "subscription_acknowledged": batch.subscription_acknowledged,
        "heartbeat_count": batch.heartbeat_count,
        "message_count": batch.message_count,
        "requested_symbols": list(batch.requested_symbols),
        "all_executable": all(
            row.executable for row in ingress_results
        ),
        "assets": [
            {
                "asset_id": quote.asset_id,
                "source_id": quote.source_id,
                "venue": quote.venue,
                "bid": quote.bid,
                "ask": quote.ask,
                "last": quote.last,
                "mark": quote.mark,
                "exchange_ts": (
                    None
                    if quote.exchange_ts is None
                    else quote.exchange_ts.isoformat()
                ),
                "received_ts": quote.received_ts.isoformat(),
                "adapter_version": quote.adapter_version,
                "ingress_attempt_id": by_asset[quote.asset_id].attempt_id,
                "runtime_registry_binding_hash": (
                    by_asset[
                        quote.asset_id
                    ].runtime_registry_binding_hash
                ),
                "executable": by_asset[quote.asset_id].executable,
                "reason": by_asset[quote.asset_id].reason,
                "calendar_reason": by_asset[quote.asset_id].calendar_reason,
                "attempted_sources": list(
                    by_asset[quote.asset_id].attempted_sources
                ),
                "rejection_reasons": list(
                    by_asset[quote.asset_id].rejection_reasons
                ),
            }
            for quote in batch.quotes
        ],
    }


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    assets: tuple[str, ...],
    timeout_s: float,
    require_executable: bool,
    output: str | None,
) -> int:
    batch = await fetch_kraken_public_tickers(
        assets=assets,
        timeout_s=timeout_s,
    )
    as_of_utc = datetime.now(timezone.utc)
    store = VNextStore(schema="aether_vnext")
    ingress_results = []

    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            def persist(sync_conn):
                for quote in batch.quotes:
                    ingress_results.append(
                        ingest_market_quotes(
                            sync_conn,
                            store,
                            asset_id=quote.asset_id,
                            quotes=(quote,),
                            calendar_provider=None,
                            as_of_utc=as_of_utc,
                            created_at_utc=as_of_utc,
                        )
                    )
            await connection.run_sync(persist)

    payload = _serialize_batch(batch, tuple(ingress_results))
    _emit(payload, output)
    if require_executable and not payload["all_executable"]:
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets",
        default="btc,eth",
        help="comma-separated AETHER crypto asset IDs; current support: btc,eth",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--require-executable", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    assets = tuple(
        value.strip().lower()
        for value in str(args.assets).split(",")
        if value.strip()
    )
    raise SystemExit(
        asyncio.run(
            _main(
                assets=assets,
                timeout_s=args.timeout_seconds,
                require_executable=args.require_executable,
                output=args.output,
            )
        )
    )
