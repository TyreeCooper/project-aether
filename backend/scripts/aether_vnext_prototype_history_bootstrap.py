"""Guarded BTC/ETH prototype-history bootstrap.

This operation mutates only the isolated aether_vnext.prototype_market_bars ledger.
It does not reset capital, alter the paper epoch, create setups/tickets/fills, or
write held-out/Phase-18 research evidence.

Recent decision-critical 1h bars and all daily trend bars come from Kraken REST.
Older Coinbase candles only extend the 90-day RV14 warm-up before Kraken's REST
hourly window begins.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import sqlalchemy as sa

from aether_vnext.coinbase_prototype_history import fetch_coinbase_hourly_history
from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.prototype_crypto_warmup import assemble_prototype_crypto_warmup
from aether_vnext.prototype_history_sources import (
    fetch_kraken_completed_daily,
    fetch_kraken_completed_hourly,
)
from aether_vnext.prototype_market_history import (
    load_prototype_market_bars,
    persist_prototype_market_bars,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
CONFIRMATION = "BOOTSTRAP-VNEXT-PROTOTYPE-HISTORY"
EXPECTED_EPOCH = "aether-prototype-new-system-test-001"


def _feature_summary(warmup) -> dict[str, object]:
    feature = warmup.feature_snapshot
    return {
        "asset_id": feature.asset_id,
        "trigger_close_utc": feature.trigger_close_utc.isoformat(),
        "close": feature.close,
        "atr14": feature.atr14,
        "prior_20h_high": feature.prior_20h_high,
        "prior_20h_low": feature.prior_20h_low,
        "daily_ema20": feature.daily_ema20,
        "daily_ema50": feature.daily_ema50,
        "btc_daily_close": feature.btc_daily_close,
        "btc_daily_ema50": feature.btc_daily_ema50,
        "volatility_percentile": feature.volatility.percentile,
        "volatility_reference_count": feature.volatility.reference_count,
        "watch_eligible": feature.watch_eligible,
        "structure_rule": feature.family_a.structure_rule,
        "regime_eligible": feature.family_a.regime_eligible,
        "dependency_ok": feature.family_a.dependency_ok,
    }


async def _fetch_inputs(as_of_utc: datetime):
    btc_coinbase = await fetch_coinbase_hourly_history(
        asset_id="btc",
        end_at_utc=as_of_utc,
        minimum_bars=2200,
    )
    eth_coinbase = await fetch_coinbase_hourly_history(
        asset_id="eth",
        end_at_utc=as_of_utc,
        minimum_bars=2200,
    )
    btc_hourly = await fetch_kraken_completed_hourly(
        asset_id="btc",
        end_at_utc=as_of_utc,
    )
    eth_hourly = await fetch_kraken_completed_hourly(
        asset_id="eth",
        end_at_utc=as_of_utc,
    )
    btc_daily = await fetch_kraken_completed_daily(
        asset_id="btc",
        end_at_utc=as_of_utc,
    )
    eth_daily = await fetch_kraken_completed_daily(
        asset_id="eth",
        end_at_utc=as_of_utc,
    )
    return {
        "btc_coinbase": btc_coinbase,
        "eth_coinbase": eth_coinbase,
        "btc_hourly": btc_hourly,
        "eth_hourly": eth_hourly,
        "btc_daily": btc_daily,
        "eth_daily": eth_daily,
    }


async def run(*, execute: bool, confirmation: str | None) -> dict[str, object]:
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype history bootstrap requires PAPER_ONLY/LIVE_BLOCKED")
    if execute and confirmation != CONFIRMATION:
        raise RuntimeError("exact prototype-history confirmation token required")

    as_of_utc = datetime.now(UTC)
    inputs = await _fetch_inputs(as_of_utc)

    btc = assemble_prototype_crypto_warmup(
        asset_id="btc",
        coinbase_hourly=inputs["btc_coinbase"],
        kraken_hourly=inputs["btc_hourly"],
        asset_kraken_daily=inputs["btc_daily"],
        btc_kraken_daily=inputs["btc_daily"],
        as_of_utc=as_of_utc,
    )
    eth = assemble_prototype_crypto_warmup(
        asset_id="eth",
        coinbase_hourly=inputs["eth_coinbase"],
        kraken_hourly=inputs["eth_hourly"],
        asset_kraken_daily=inputs["eth_daily"],
        btc_kraken_daily=inputs["btc_daily"],
        as_of_utc=as_of_utc,
    )

    store = VNextStore(schema="aether_vnext")
    before_count = 0
    inserted_count = 0
    after_count = 0
    epoch_before = None
    epoch_after = None

    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            def mutate_or_preview(sync_conn):
                nonlocal before_count, inserted_count, after_count
                nonlocal epoch_before, epoch_after

                table = store.tables["prototype_market_bars"]
                before_count = int(
                    sync_conn.execute(
                        sa.select(sa.func.count()).select_from(table)
                    ).scalar_one()
                )

                epoch_before = store.current_paper_test_epoch(sync_conn)
                if epoch_before is None:
                    raise RuntimeError("prototype paper epoch is missing")
                if str(epoch_before["epoch_id"]) != EXPECTED_EPOCH:
                    raise RuntimeError(
                        "prototype paper epoch changed before history bootstrap"
                    )
                if not bool(epoch_before["paper_only"]) or not bool(
                    epoch_before["live_blocked"]
                ):
                    raise RuntimeError("paper epoch safety flags changed")

                if execute:
                    rows = (
                        *btc.hourly_bars,
                        *eth.hourly_bars,
                        *inputs["btc_daily"],
                        *inputs["eth_daily"],
                    )
                    inserted_count = persist_prototype_market_bars(
                        sync_conn,
                        store,
                        tuple(rows),
                        ingested_at_utc=as_of_utc,
                    )

                after_count = int(
                    sync_conn.execute(
                        sa.select(sa.func.count()).select_from(table)
                    ).scalar_one()
                )
                epoch_after = store.current_paper_test_epoch(sync_conn)

            await connection.run_sync(mutate_or_preview)

    if epoch_after is None or str(epoch_after["epoch_id"]) != EXPECTED_EPOCH:
        raise RuntimeError("prototype paper epoch changed during history bootstrap")

    return {
        "mode": "executed" if execute else "preview",
        "mutation_performed": bool(execute),
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
        "phase18_evidence": False,
        "paper_epoch_id": EXPECTED_EPOCH,
        "as_of_utc": as_of_utc.isoformat(),
        "prototype_market_bar_count_before": before_count,
        "prototype_market_bar_count_after": after_count,
        "inserted_count": inserted_count,
        "btc": {
            "hourly_total": len(btc.hourly_bars),
            "coinbase_reference_bar_count": btc.coinbase_reference_bar_count,
            "kraken_hourly_bar_count": btc.kraken_hourly_bar_count,
            "kraken_daily_bar_count": len(inputs["btc_daily"]),
            "features": _feature_summary(btc),
        },
        "eth": {
            "hourly_total": len(eth.hourly_bars),
            "coinbase_reference_bar_count": eth.coinbase_reference_bar_count,
            "kraken_hourly_bar_count": eth.kraken_hourly_bar_count,
            "kraken_daily_bar_count": len(inputs["eth_daily"]),
            "features": _feature_summary(eth),
        },
    }


def main(*, execute: bool, confirmation: str | None, output: str) -> int:
    body = asyncio.run(run(execute=execute, confirmation=confirmation))
    rendered = json.dumps(body, indent=2, sort_keys=True)
    Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument(
        "--output",
        default="aether-vnext-prototype-history-bootstrap.json",
    )
    args = parser.parse_args()
    raise SystemExit(
        main(
            execute=args.execute,
            confirmation=args.confirm,
            output=args.output,
        )
    )
