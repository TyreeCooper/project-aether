"""Autonomous Kraken market-ingress supervisor for the vNext prototype.

This worker is deliberately market-data-only. It may fetch public BTC/ETH quotes and
run them through the canonical vNext ingress boundary, but it has no authority to
create setups, tickets, order intents, fills, or live orders.

It is disabled by default and may only be enabled in the dedicated burn-in
environment. Missing runtime Product Registry bindings remain fail-closed and are
recorded as ingress-attempt blockers rather than bypassed.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from typing import Awaitable, Callable, Mapping, Sequence

from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.kraken_public import (
    CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL,
    KRAKEN_PUBLIC_TICKER_SOURCE_ID,
    fetch_kraken_public_tickers,
)
from aether_vnext.market_ingress import ingest_market_quotes
from aether_vnext.store import VNextStore


CycleRunner = Callable[[], Awaitable[dict[str, object]]]
CRYPTO_ASSETS = ("btc", "eth")


@dataclass(frozen=True, slots=True)
class KrakenIngressSupervisorStatus:
    enabled: bool
    running: bool
    paper_only: bool
    live_blocked: bool
    cycle_count: int
    interval_seconds: float
    last_cycle_started_at_utc: str | None
    last_cycle_finished_at_utc: str | None
    last_error: str | None
    last_result: dict[str, object] | None


class KrakenIngressSupervisor:
    def __init__(
        self,
        *,
        cycle_runner: CycleRunner,
        interval_seconds: float = 15.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._cycle_runner = cycle_runner
        self._interval_seconds = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._cycle_count = 0
        self._last_started: datetime | None = None
        self._last_finished: datetime | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, object] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self, *, enabled: bool = True) -> KrakenIngressSupervisorStatus:
        return KrakenIngressSupervisorStatus(
            enabled=enabled,
            running=self.running,
            paper_only=PAPER_ONLY,
            live_blocked=LIVE_BLOCKED,
            cycle_count=self._cycle_count,
            interval_seconds=self._interval_seconds,
            last_cycle_started_at_utc=(
                None if self._last_started is None else self._last_started.isoformat()
            ),
            last_cycle_finished_at_utc=(
                None if self._last_finished is None else self._last_finished.isoformat()
            ),
            last_error=self._last_error,
            last_result=self._last_result,
        )

    async def start(self) -> None:
        if self.running:
            return
        if not PAPER_ONLY or not LIVE_BLOCKED:
            raise RuntimeError("vNext ingress requires PAPER_ONLY and LIVE_BLOCKED")
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="aether-vnext-kraken-ingress",
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._last_started = datetime.now(timezone.utc)
            try:
                result = await self._cycle_runner()
                self._last_result = dict(result)
                self._last_error = None
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Fail closed but keep the market-data supervisor alive so a
                # transient provider/database fault cannot silently kill telemetry.
                self._last_error = f"{type(exc).__name__}:{exc}"
            finally:
                self._last_finished = datetime.now(timezone.utc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue


def _quote_telemetry(
    quote: object,
    *,
    symbol_by_asset: Mapping[str, str] | None = None,
) -> dict[str, object]:
    asset_id = str(getattr(quote, "asset_id")).strip().lower()
    exchange_ts = getattr(quote, "exchange_ts")
    received_ts = getattr(quote, "received_ts")
    reference_ts = exchange_ts or received_ts
    symbols = dict(CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL)
    if symbol_by_asset is not None:
        symbols.update({
            str(key).strip().lower(): str(value).strip()
            for key, value in symbol_by_asset.items()
        })
    return {
        "asset_id": asset_id,
        "symbol": symbols.get(asset_id),
        "bid": getattr(quote, "bid"),
        "ask": getattr(quote, "ask"),
        "last": getattr(quote, "last"),
        "mark": getattr(quote, "mark"),
        "exchange_ts_utc": (
            None if exchange_ts is None else exchange_ts.isoformat()
        ),
        "received_ts_utc": received_ts.isoformat(),
        "reference_ts_utc": reference_ts.isoformat(),
        "source_id": str(getattr(quote, "source_id")),
        "venue": str(getattr(quote, "venue")),
    }


def _dynamic_kraken_symbol_map(
    states: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    """Select only verified Kraken-public USD spot products for ticker ingress."""
    out: dict[str, str] = {}
    seen_symbols: set[str] = set()
    for state in states:
        product = state.get("product")
        if product is None:
            continue
        asset_id = str(getattr(product, "asset_id", "") or "").strip().lower()
        symbol = str(getattr(product, "canonical_symbol", "") or "").strip()
        if (
            not asset_id
            or not symbol
            or asset_id in CRYPTO_ASSETS
            or str(getattr(product, "broker", "") or "") != "Kraken"
            or str(getattr(product, "venue", "") or "") != "Kraken"
            or str(getattr(product, "quote_currency", "") or "").upper() != "USD"
            or str(getattr(product, "settlement_currency", "") or "").upper() != "USD"
            or str(getattr(product, "primary_market_source_id", "") or "")
                != KRAKEN_PUBLIC_TICKER_SOURCE_ID
            or not bool(product.market_data_ready())
        ):
            continue
        if symbol in seen_symbols:
            raise RuntimeError(f"duplicate dynamic Kraken symbol: {symbol}")
        seen_symbols.add(symbol)
        out[asset_id] = symbol
    return dict(sorted(out.items()))


def _chunks(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return tuple(
        values[start:start + size]
        for start in range(0, len(values), size)
    )


async def run_configured_kraken_ingress_cycle() -> dict[str, object]:
    """Ingest seed plus verified dynamic Kraken BBO using bounded subscriptions."""
    store = VNextStore(schema="aether_vnext")
    results: list[dict[str, object]] = []
    all_quotes: list[object] = []
    batch_errors: list[dict[str, object]] = []

    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            dynamic_states = await connection.run_sync(
                lambda sync_conn: store.list_dynamic_product_states(sync_conn)
            )

        dynamic_symbols = _dynamic_kraken_symbol_map(dynamic_states)
        symbol_by_asset = {
            **CRYPTO_ASSET_TO_KRAKEN_V2_SYMBOL,
            **dynamic_symbols,
        }

        # Keep the canonical seed lane isolated so a dynamic subscription problem
        # can never starve BTC/ETH market truth.
        seed_batch = await fetch_kraken_public_tickers(
            assets=CRYPTO_ASSETS,
            timeout_s=10.0,
        )
        all_quotes.extend(seed_batch.quotes)

        dynamic_assets = tuple(dynamic_symbols)
        for chunk in _chunks(
            dynamic_assets,
            configured_dynamic_ingress_batch_size(),
        ):
            chunk_symbols = {asset: dynamic_symbols[asset] for asset in chunk}
            try:
                dynamic_batch = await fetch_kraken_public_tickers(
                    assets=chunk,
                    symbol_by_asset=chunk_symbols,
                    timeout_s=10.0,
                )
                all_quotes.extend(dynamic_batch.quotes)
            except Exception as exc:
                # A failed dynamic batch becomes explicit quote_missing attempts;
                # the seed lane and every other dynamic batch keep running.
                batch_errors.append({
                    "assets": list(chunk),
                    "error": f"{type(exc).__name__}:{exc}",
                })

        attempted_assets = CRYPTO_ASSETS + dynamic_assets
        quote_rows = tuple(all_quotes)
        async with engine.begin() as connection:
            for asset_id in attempted_assets:
                # Decide only after provider I/O has completed. Capturing this
                # timestamp before an awaited fetch made every newly received
                # quote appear to come from the future.
                asset_as_of_utc = datetime.now(timezone.utc)
                result = await connection.run_sync(
                    lambda sync_conn, aid=asset_id, now=asset_as_of_utc: ingest_market_quotes(
                        sync_conn,
                        store,
                        asset_id=aid,
                        quotes=quote_rows,
                        calendar_provider=None,
                        as_of_utc=now,
                    )
                )
                results.append(
                    {
                        "asset_id": result.asset_id,
                        "executable": result.executable,
                        "reason": result.reason,
                        "observation_id": (
                            None
                            if result.observation is None
                            else result.observation.observation_id
                        ),
                        "rejection_reasons": list(result.rejection_reasons),
                    }
                )

    return {
        "provider": "kraken_public",
        "status_system": seed_batch.status_system,
        "subscription_acknowledged": seed_batch.subscription_acknowledged,
        "seed_asset_count": len(CRYPTO_ASSETS),
        "dynamic_asset_count": len(dynamic_assets),
        "attempted_asset_count": len(CRYPTO_ASSETS) + len(dynamic_assets),
        "quoted_asset_count": len({
            str(getattr(quote, "asset_id")).strip().lower()
            for quote in all_quotes
        }),
        "batch_errors": batch_errors,
        "asset_results": results,
        "quotes": [
            _quote_telemetry(quote, symbol_by_asset=symbol_by_asset)
            for quote in all_quotes
        ],
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
    }


def configured_dynamic_ingress_batch_size() -> int:
    raw = os.getenv("AETHER_VNEXT_KRAKEN_DYNAMIC_BATCH_SIZE", "20").strip()
    value = int(raw)
    if value < 1 or value > 50:
        raise ValueError(
            "AETHER_VNEXT_KRAKEN_DYNAMIC_BATCH_SIZE must be between 1 and 50"
        )
    return value


def configured_ingress_enabled() -> bool:
    raw = os.getenv("AETHER_VNEXT_KRAKEN_INGRESS_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def configured_ingress_interval_seconds() -> float:
    raw = os.getenv("AETHER_VNEXT_KRAKEN_INGRESS_INTERVAL_SECONDS", "15").strip()
    value = float(raw)
    if value < 5.0:
        raise ValueError("AETHER_VNEXT_KRAKEN_INGRESS_INTERVAL_SECONDS must be >= 5")
    return value


def validate_configured_ingress_environment() -> None:
    if not configured_ingress_enabled():
        return
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "burnin":
        raise RuntimeError("vNext Kraken ingress may only run in burnin")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("vNext Kraken ingress safety invariant failed")
    # Parse configuration before starting the task so a missing/invalid dedicated
    # database fails startup instead of falling back to legacy state.
    VNextDatabaseConfig.from_environment()


def status_payload(
    status: KrakenIngressSupervisorStatus,
) -> dict[str, object]:
    return asdict(status)
