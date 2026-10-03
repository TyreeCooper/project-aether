"""Probe reviewed IBKR equity top-of-book into canonical AETHER vNext ingress.

This is an operator/local probe, not a GitHub-hosted burn-in job. Client Portal
Gateway sessions are machine-local and manually authenticated; OAuth2 deployments
may supply a different WebSocket URL explicitly.

The probe:
1. loads durable NVDA/TSLA/PLTR runtime bindings;
2. requires IBKR market-data source + reviewed conid + TradingHours market identity;
3. prefetches the authoritative calendar snapshot for the current ET session date;
4. fetches one real-time IBKR top-of-book sample per configured equity;
5. independently requires one provider-authored Last Price + Last Size trade print;
6. persists each quote sample through canonical market_ingress.

No order, position, account-mutation, or LIVE execution methods are used.
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
from aether_vnext.ibkr_webapi_market import (
    IBKR_CPGW_WEBSOCKET_URL,
    IBKR_WEBAPI_MARKET_SOURCE_ID,
    IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
    fetch_ibkr_shortability,
    fetch_ibkr_top_of_book,
    fetch_ibkr_trade_prints,
)
from aether_vnext.market_ingress import ingest_market_quotes
from aether_vnext.registry import registry_row
from aether_vnext.store import VNextStore
from aether_vnext.tradinghours_calendar import (
    TRADINGHOURS_CALENDAR_PROVIDER_ID,
    TradingHoursCalendarProvider,
    fetch_tradinghours_calendar_snapshot,
)


ET = ZoneInfo("America/New_York")
_EQUITIES = frozenset({"nvda", "tsla", "pltr"})


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _selected_bindings(
    rows: tuple[dict, ...],
    *,
    requested_assets: tuple[str, ...],
) -> tuple[dict, ...]:
    requested = tuple(str(value).strip().lower() for value in requested_assets)
    if not requested:
        raise ValueError("at least one equity asset is required")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate requested asset")
    unsupported = tuple(value for value in requested if value not in _EQUITIES)
    if unsupported:
        raise ValueError(
            "IBKR equity probe supports only nvda,tsla,pltr: "
            + ",".join(unsupported)
        )

    by_asset = {
        row["binding"].asset_id.strip().lower(): row
        for row in rows
        if row["binding"].asset_id.strip().lower() in _EQUITIES
    }
    selected: list[dict] = []
    for asset_id in requested:
        row = by_asset.get(asset_id)
        if row is None:
            raise RuntimeError(
                f"durable runtime binding missing for IBKR equity: {asset_id}"
            )
        binding = row["binding"]
        if binding.primary_market_source_id != IBKR_WEBAPI_MARKET_SOURCE_ID:
            raise RuntimeError(
                f"{asset_id} primary market source is not IBKR Web API"
            )
        if binding.market_data_contract_id is None:
            raise RuntimeError(
                f"{asset_id} reviewed IBKR conid is missing"
            )
        if (
            binding.shortability_provider_id
            != IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID
        ):
            raise RuntimeError(
                f"{asset_id} shortability provider is not IBKR Web API"
            )
        if binding.shortability_stale_threshold_ms is None:
            raise RuntimeError(
                f"{asset_id} shortability stale threshold is missing"
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


def _contract_map(rows: tuple[dict, ...]) -> dict[str, int]:
    return {
        row["binding"].asset_id.strip().lower(): int(
            row["binding"].market_data_contract_id
        )
        for row in rows
    }


def _serialize(
    batch,
    trade_print_batch,
    shortability_batch,
    ingress_results,
) -> dict[str, object]:
    by_asset = {row.asset_id: row for row in ingress_results}
    shortability_by_asset = {
        row.asset_id: row for row in shortability_batch.evidence
    }
    trade_print_by_asset = {
        row.asset_id: row for row in trade_print_batch.prints
    }
    return {
        "provider": "IBKR",
        "transport": "webapi_smd_websocket",
        "auth_mode": batch.auth_mode,
        "websocket_url": batch.websocket_url,
        "message_count": batch.message_count,
        "requested_contract_ids": list(batch.requested_contract_ids),
        "all_executable": all(row.executable for row in ingress_results),
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
                    by_asset[quote.asset_id].runtime_registry_binding_hash
                ),
                "executable": by_asset[quote.asset_id].executable,
                "reason": by_asset[quote.asset_id].reason,
                "calendar_reason": by_asset[quote.asset_id].calendar_reason,
                "rejection_reasons": list(
                    by_asset[quote.asset_id].rejection_reasons
                ),
                "trade_print": {
                    "price": trade_print_by_asset[quote.asset_id].price,
                    "volume": trade_print_by_asset[quote.asset_id].volume,
                    "exchange_ts": trade_print_by_asset[
                        quote.asset_id
                    ].exchange_ts.isoformat(),
                    "received_ts": trade_print_by_asset[
                        quote.asset_id
                    ].received_ts.isoformat(),
                    "source_id": trade_print_by_asset[
                        quote.asset_id
                    ].source_id,
                },
                "shortability": {
                    "evidence_id": shortability_by_asset[
                        quote.asset_id
                    ].evidence_id,
                    "shortable_shares": shortability_by_asset[
                        quote.asset_id
                    ].shortable_shares,
                    "fee_rate_raw": shortability_by_asset[
                        quote.asset_id
                    ].fee_rate_raw,
                    "shortable_raw": shortability_by_asset[
                        quote.asset_id
                    ].shortable_raw,
                    "market_data_availability": shortability_by_asset[
                        quote.asset_id
                    ].market_data_availability,
                    "provider_updated_at_utc": (
                        None
                        if shortability_by_asset[
                            quote.asset_id
                        ].provider_updated_at_utc is None
                        else shortability_by_asset[
                            quote.asset_id
                        ].provider_updated_at_utc.isoformat()
                    ),
                    "received_at_utc": shortability_by_asset[
                        quote.asset_id
                    ].received_at_utc.isoformat(),
                },
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
    session_token = os.getenv(
        "AETHER_VNEXT_IBKR_SESSION_TOKEN",
        "",
    ).strip()
    if not session_token:
        raise RuntimeError("AETHER_VNEXT_IBKR_SESSION_TOKEN is required")

    tradinghours_token = os.getenv(
        "AETHER_VNEXT_TRADINGHOURS_API_TOKEN",
        "",
    ).strip()
    if not tradinghours_token:
        raise RuntimeError("AETHER_VNEXT_TRADINGHOURS_API_TOKEN is required")

    auth_mode = os.getenv(
        "AETHER_VNEXT_IBKR_AUTH_MODE",
        "",
    ).strip()
    if not auth_mode:
        raise RuntimeError(
            "AETHER_VNEXT_IBKR_AUTH_MODE must be cpgw_cookie or oauth2_query"
        )

    websocket_url = os.getenv(
        "AETHER_VNEXT_IBKR_WEBSOCKET_URL",
        IBKR_CPGW_WEBSOCKET_URL,
    ).strip()
    allow_insecure = _truthy(
        os.getenv("AETHER_VNEXT_IBKR_ALLOW_INSECURE_LOCALHOST_TLS")
    )

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

        contract_map = _contract_map(selected)
        batch = await fetch_ibkr_top_of_book(
            asset_contract_ids=contract_map,
            session_token=session_token,
            auth_mode=auth_mode,
            websocket_url=websocket_url,
            timeout_s=timeout_s,
            allow_insecure_localhost_tls=allow_insecure,
        )
        trade_print_batch = await fetch_ibkr_trade_prints(
            asset_contract_ids=contract_map,
            session_token=session_token,
            auth_mode=auth_mode,
            websocket_url=websocket_url,
            timeout_s=timeout_s,
            allow_insecure_localhost_tls=allow_insecure,
        )
        shortability_batch = await fetch_ibkr_shortability(
            asset_contract_ids=contract_map,
            session_token=session_token,
            auth_mode=auth_mode,
            websocket_url=websocket_url,
            timeout_s=timeout_s,
            allow_insecure_localhost_tls=allow_insecure,
        )

        ingress_results = []
        as_of_utc = datetime.now(timezone.utc)
        selected_by_asset = {
            row["binding"].asset_id.strip().lower(): row
            for row in selected
        }
        async with engine.begin() as connection:
            def persist(sync_conn):
                for evidence in shortability_batch.evidence:
                    runtime_row = selected_by_asset[evidence.asset_id]
                    store.record_shortability_evidence(
                        sync_conn,
                        evidence,
                        configuration_hash=str(
                            runtime_row["configuration_hash"]
                        ),
                        runtime_registry_binding_hash=str(
                            runtime_row["binding_hash"]
                        ),
                        created_at_utc=as_of_utc,
                    )
                for quote in batch.quotes:
                    ingress_results.append(
                        ingest_market_quotes(
                            sync_conn,
                            store,
                            asset_id=quote.asset_id,
                            quotes=(quote,),
                            calendar_provider=calendar_provider,
                            as_of_utc=as_of_utc,
                            created_at_utc=as_of_utc,
                        )
                    )
            await connection.run_sync(persist)

    payload = _serialize(
        batch,
        trade_print_batch,
        shortability_batch,
        tuple(ingress_results),
    )
    _emit(payload, output)
    if require_executable and not payload["all_executable"]:
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets",
        default="nvda,tsla,pltr",
        help="comma-separated AETHER equity asset IDs",
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
