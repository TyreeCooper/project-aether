"""Probe NinjaTrader DEMO futures quotes into canonical AETHER vNext ingress.

This operator probe accepts only the market-data-only NinjaTrader authentication
payload consumed by NinjaTraderDemoMarketAuth. Trading accessToken and live hosts are
rejected by that boundary before any socket connection.

For each requested futures asset the probe:
- loads the durable reviewed contract symbol + numeric market-data contract ID;
- prefetches the configured TradingHours calendar snapshot;
- retrieves one DEMO BBO quote from the reviewed contract;
- persists the quote through canonical market_ingress.

No order, account, position, or live-trading endpoint is used.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.market_ingress import ingest_market_quotes
from aether_vnext.ninjatrader_demo import (
    NinjaTraderDemoMarketAuth,
    fetch_ninjatrader_demo_quote,
)
from aether_vnext.ninjatrader_market import NINJATRADER_MARKET_SOURCE_ID
from aether_vnext.registry import registry_row
from aether_vnext.store import VNextStore
from aether_vnext.tradinghours_calendar import (
    TRADINGHOURS_CALENDAR_PROVIDER_ID,
    TradingHoursCalendarProvider,
    fetch_tradinghours_calendar_snapshot,
)


ET = ZoneInfo("America/New_York")
_FUTURES = frozenset({"mes", "mnq", "mgc", "mcl", "us10y"})


def _load_auth(raw: str) -> NinjaTraderDemoMarketAuth:
    text = str(raw).strip()
    if not text:
        raise RuntimeError(
            "AETHER_VNEXT_NINJATRADER_MARKET_AUTH_JSON is required"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("NinjaTrader market auth JSON is invalid") from exc
    return NinjaTraderDemoMarketAuth.from_market_only_payload(payload)


def _selected_bindings(
    rows: tuple[dict, ...],
    *,
    requested_assets: tuple[str, ...],
) -> tuple[dict, ...]:
    requested = tuple(str(value).strip().lower() for value in requested_assets)
    if not requested:
        raise ValueError("at least one futures asset is required")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate requested asset")
    unsupported = tuple(value for value in requested if value not in _FUTURES)
    if unsupported:
        raise ValueError(
            "NinjaTrader futures probe supports mes,mnq,mgc,mcl,us10y: "
            + ",".join(unsupported)
        )

    by_asset = {
        row["binding"].asset_id.strip().lower(): row
        for row in rows
        if row["binding"].asset_id.strip().lower() in _FUTURES
    }
    selected: list[dict] = []
    for asset_id in requested:
        row = by_asset.get(asset_id)
        if row is None:
            raise RuntimeError(
                f"durable runtime binding missing for futures asset: {asset_id}"
            )
        binding = row["binding"]
        if binding.primary_market_source_id != NINJATRADER_MARKET_SOURCE_ID:
            raise RuntimeError(
                f"{asset_id} primary source is not NinjaTrader market data"
            )
        if not str(binding.current_contract or "").strip():
            raise RuntimeError(f"{asset_id} current futures contract is missing")
        if binding.market_data_contract_id is None:
            raise RuntimeError(
                f"{asset_id} reviewed NinjaTrader contractId is missing"
            )
        if binding.calendar_provider_id != TRADINGHOURS_CALENDAR_PROVIDER_ID:
            raise RuntimeError(
                f"{asset_id} calendar provider is not TradingHours"
            )
        if not str(binding.calendar_market_id or "").strip():
            raise RuntimeError(
                f"{asset_id} TradingHours market identity is missing"
            )
        selected.append(row)
    return tuple(selected)


def _calendar_map(rows: tuple[dict, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        binding = row["binding"]
        calendar_id = registry_row(binding.asset_id).calendar_id
        market_id = str(binding.calendar_market_id or "").strip()
        existing = out.get(calendar_id)
        if existing is not None and existing != market_id:
            raise RuntimeError(
                f"conflicting TradingHours market identity for {calendar_id}"
            )
        out[calendar_id] = market_id
    return out


def _serialize(samples, ingress_results) -> dict[str, object]:
    by_asset = {row.asset_id: row for row in ingress_results}
    return {
        "provider": "NinjaTrader",
        "transport": "DEMO_market_websocket",
        "market_source_id": NINJATRADER_MARKET_SOURCE_ID,
        "all_executable": all(row.executable for row in ingress_results),
        "assets": [
            {
                "asset_id": sample.asset_id,
                "current_contract": sample.current_contract,
                "contract_id": sample.contract_id,
                "endpoint": sample.endpoint,
                "heartbeat_count": sample.heartbeat_count,
                "message_count": sample.message_count,
                "bid": sample.quote.bid,
                "ask": sample.quote.ask,
                "last": sample.quote.last,
                "mark": sample.quote.mark,
                "exchange_ts": (
                    None
                    if sample.quote.exchange_ts is None
                    else sample.quote.exchange_ts.isoformat()
                ),
                "received_ts": sample.quote.received_ts.isoformat(),
                "adapter_version": sample.quote.adapter_version,
                "ingress_attempt_id": by_asset[
                    sample.asset_id
                ].attempt_id,
                "runtime_registry_binding_hash": by_asset[
                    sample.asset_id
                ].runtime_registry_binding_hash,
                "executable": by_asset[sample.asset_id].executable,
                "reason": by_asset[sample.asset_id].reason,
                "calendar_reason": by_asset[
                    sample.asset_id
                ].calendar_reason,
                "rejection_reasons": list(
                    by_asset[sample.asset_id].rejection_reasons
                ),
            }
            for sample in samples
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
    auth = _load_auth(
        os.getenv("AETHER_VNEXT_NINJATRADER_MARKET_AUTH_JSON", "")
    )
    tradinghours_token = os.getenv(
        "AETHER_VNEXT_TRADINGHOURS_API_TOKEN",
        "",
    ).strip()
    if not tradinghours_token:
        raise RuntimeError("AETHER_VNEXT_TRADINGHOURS_API_TOKEN is required")

    now = datetime.now(timezone.utc)
    session_date = now.astimezone(ET).date()
    store = VNextStore(schema="aether_vnext")

    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            rows = await connection.run_sync(
                lambda sync_conn: store.list_runtime_registry_bindings(sync_conn)
            )

        selected = _selected_bindings(
            rows,
            requested_assets=assets,
        )
        calendar_snapshot = await fetch_tradinghours_calendar_snapshot(
            api_token=tradinghours_token,
            calendar_market_ids=_calendar_map(selected),
            session_dates=(session_date,),
            fetched_at_utc=now,
        )
        calendar_provider = TradingHoursCalendarProvider(calendar_snapshot)

        samples = []
        for row in selected:
            samples.append(
                await fetch_ninjatrader_demo_quote(
                    binding=row["binding"],
                    auth=auth,
                    timeout_s=timeout_s,
                )
            )

        ingress_results = []
        as_of_utc = datetime.now(timezone.utc)
        async with engine.begin() as connection:
            def persist(sync_conn):
                for sample in samples:
                    ingress_results.append(
                        ingest_market_quotes(
                            sync_conn,
                            store,
                            asset_id=sample.asset_id,
                            quotes=(sample.quote,),
                            calendar_provider=calendar_provider,
                            as_of_utc=as_of_utc,
                            created_at_utc=as_of_utc,
                        )
                    )
            await connection.run_sync(persist)

    payload = _serialize(tuple(samples), tuple(ingress_results))
    _emit(payload, output)
    if require_executable and not payload["all_executable"]:
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets",
        default="mes,mnq,mgc,mcl,us10y",
        help="comma-separated AETHER futures asset IDs",
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
