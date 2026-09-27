"""Apply reviewed external Product Registry bindings to the vNext book.

This command never invents provider IDs, stale thresholds, executable symbols,
futures contracts, expiries, calendars, or locate sources. It persists exactly the
operator-supplied manifest and reports completeness blockers per asset.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.registry_runtime import (
    RuntimeRegistryBinding,
    binding_blockers,
    binding_hash,
    runtime_binding_universe,
    runtime_binding_universe_blockers,
)
from aether_vnext.store import VNextStore


def _load_payload(*, manifest_json: str | None, manifest_file: str | None) -> dict:
    if (manifest_json is None) == (manifest_file is None):
        raise ValueError("choose exactly one of --manifest-json or --manifest-file")
    raw = (
        manifest_json
        if manifest_json is not None
        else Path(str(manifest_file)).read_text(encoding="utf-8")
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return payload


def _binding(row: object) -> RuntimeRegistryBinding:
    if not isinstance(row, dict):
        raise ValueError("each binding must be a JSON object")
    expiry_raw = row.get("expiry_utc")
    expiry = None
    if expiry_raw not in (None, ""):
        expiry = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
    stale_raw = row.get("stale_threshold_ms")
    stale = None if stale_raw in (None, "") else int(stale_raw)
    contract_id_raw = row.get("market_data_contract_id")
    market_data_contract_id = (
        None
        if contract_id_raw in (None, "")
        else int(contract_id_raw)
    )
    shortability_stale_raw = row.get("shortability_stale_threshold_ms")
    shortability_stale = (
        None
        if shortability_stale_raw in (None, "")
        else int(shortability_stale_raw)
    )
    return RuntimeRegistryBinding(
        asset_id=str(row.get("asset_id") or ""),
        broker_symbol=row.get("broker_symbol"),
        primary_market_source_id=row.get("primary_market_source_id"),
        fallback_market_source_id=row.get("fallback_market_source_id"),
        stale_threshold_ms=stale,
        calendar_provider_id=row.get("calendar_provider_id"),
        calendar_market_id=row.get("calendar_market_id"),
        current_contract=row.get("current_contract"),
        market_data_contract_id=market_data_contract_id,
        expiry_utc=expiry,
        next_contract=row.get("next_contract"),
        shortability_provider_id=row.get("shortability_provider_id"),
        shortability_stale_threshold_ms=shortability_stale,
        source_ref=row.get("source_ref"),
    )


def _parse_manifest(payload: dict) -> tuple[str, str, tuple[RuntimeRegistryBinding, ...]]:
    registry_version = str(payload.get("registry_version") or "").strip()
    configuration_hash = str(
        payload.get("configuration_hash") or CONFIGURATION_HASH
    ).strip()
    rows = payload.get("bindings")
    if not registry_version:
        raise ValueError("registry_version is required")
    if configuration_hash != CONFIGURATION_HASH:
        raise ValueError("runtime binding manifest configuration_hash is not canonical")
    if not isinstance(rows, list) or not rows:
        raise ValueError("bindings must be a non-empty list")
    bindings = tuple(_binding(row) for row in rows)
    asset_ids = tuple(binding.asset_id.strip().lower() for binding in bindings)
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("duplicate asset_id in runtime binding manifest")
    return registry_version, configuration_hash, bindings


def _validation_report(
    *,
    registry_version: str,
    configuration_hash: str,
    bindings: tuple[RuntimeRegistryBinding, ...],
    as_of_utc: datetime,
    require_seed_universe: bool,
    require_implemented_source: bool,
    require_implemented_calendar: bool,
    require_implemented_shortability: bool,
) -> dict[str, object]:
    universe = runtime_binding_universe(bindings)
    manifest_blockers = (
        runtime_binding_universe_blockers(bindings)
        if require_seed_universe
        else ()
    )
    rows: list[dict[str, object]] = []
    for binding in bindings:
        blockers = binding_blockers(
            binding,
            as_of_utc=as_of_utc,
            require_market_source_implementation=(
                require_implemented_source
            ),
            require_calendar_provider_implementation=(
                require_implemented_calendar
            ),
            require_shortability_provider_implementation=(
                require_implemented_shortability
            ),
        )
        rows.append(
            {
                "asset_id": binding.asset_id.strip().lower(),
                "binding_hash": binding_hash(binding),
                "blockers": list(blockers),
                "complete": not blockers,
            }
        )
    incomplete_count = sum(1 for row in rows if not row["complete"])
    return {
        "registry_version": registry_version,
        "configuration_hash": configuration_hash,
        "require_seed_universe": require_seed_universe,
        "require_implemented_source": require_implemented_source,
        "require_implemented_calendar": require_implemented_calendar,
        "require_implemented_shortability": require_implemented_shortability,
        "expected_asset_ids": list(universe.expected_asset_ids),
        "supplied_asset_ids": list(universe.supplied_asset_ids),
        "missing_asset_ids": list(universe.missing_asset_ids),
        "unexpected_asset_ids": list(universe.unexpected_asset_ids),
        "manifest_blockers": list(manifest_blockers),
        "binding_count": len(rows),
        "complete_binding_count": len(rows) - incomplete_count,
        "incomplete_binding_count": incomplete_count,
        "bindings": rows,
    }


async def _main(
    *,
    manifest_json: str | None,
    manifest_file: str | None,
    require_complete: bool,
    require_seed_universe: bool,
    require_implemented_source: bool,
    require_implemented_calendar: bool,
    require_implemented_shortability: bool,
    output: str | None,
) -> int:
    payload = _load_payload(
        manifest_json=manifest_json,
        manifest_file=manifest_file,
    )
    registry_version, configuration_hash, bindings = _parse_manifest(payload)
    now = datetime.now(timezone.utc)
    report = _validation_report(
        registry_version=registry_version,
        configuration_hash=configuration_hash,
        bindings=bindings,
        as_of_utc=now,
        require_seed_universe=require_seed_universe,
        require_implemented_source=require_implemented_source,
        require_implemented_calendar=require_implemented_calendar,
        require_implemented_shortability=require_implemented_shortability,
    )

    strict_failure = bool(report["manifest_blockers"]) or bool(
        report["incomplete_binding_count"]
    )
    if require_complete and strict_failure:
        report["persisted"] = False
    else:
        store = VNextStore(schema="aether_vnext")
        async with open_vnext_engine() as engine:
            async with engine.begin() as connection:
                def apply(sync_conn):
                    for binding in bindings:
                        digest = store.upsert_runtime_registry_binding(
                            sync_conn,
                            binding,
                            registry_version=registry_version,
                            configuration_hash=configuration_hash,
                            updated_at_utc=now,
                        )
                        expected = binding_hash(binding)
                        if digest != expected:
                            raise RuntimeError(
                                "runtime binding persistence hash drift"
                            )
                await connection.run_sync(apply)
        report["persisted"] = True
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")

    if require_complete and strict_failure:
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest-json")
    source.add_argument("--manifest-file")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument(
        "--require-seed-universe",
        action="store_true",
        help="require exactly the canonical seed-12 asset universe",
    )
    parser.add_argument(
        "--require-implemented-source",
        action="store_true",
        help="fail bindings whose reviewed source lacks a vNext implementation",
    )
    parser.add_argument(
        "--require-implemented-calendar",
        action="store_true",
        help="fail non-24x7 bindings whose calendar provider lacks vNext code",
    )
    parser.add_argument(
        "--require-implemented-shortability",
        action="store_true",
        help=(
            "fail borrow-required equity bindings whose shortability provider "
            "lacks vNext implementation"
        ),
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                manifest_json=args.manifest_json,
                manifest_file=args.manifest_file,
                require_complete=args.require_complete,
                require_seed_universe=args.require_seed_universe,
                require_implemented_source=args.require_implemented_source,
                require_implemented_calendar=args.require_implemented_calendar,
                require_implemented_shortability=(
                    args.require_implemented_shortability
                ),
                output=args.output,
            )
        )
    )
