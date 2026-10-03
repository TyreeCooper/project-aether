"""Autonomous Kraken market-ingress supervisor for the vNext sandbox.

This worker is deliberately market-data-only. It may fetch public BTC/ETH quotes and
run them through the canonical vNext ingress boundary, but it has no authority to
create setups, tickets, order intents, fills, or live orders.

It is disabled by default and may only be enabled in the dedicated burn-in
environment. Missing runtime Product Registry bindings remain fail-closed and are
recorded as ingress-attempt blockers rather than bypassed.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
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

_MAINTENANCE_QUARANTINED_SYMBOLS: set[str] = set()
_INGRESS_PROGRESS: dict[str, object] = {
    "cycle_state": "idle",
    "phase": "idle",
    "cycle_started_at_utc": None,
    "last_progress_at_utc": None,
    "eligible_asset_count": None,
    "dynamic_chunk_count": None,
    "completed_dynamic_chunk_count": 0,
    "processed_asset_count": 0,
}


def _publish_ingress_progress(**updates: object) -> None:
    global _INGRESS_PROGRESS
    _INGRESS_PROGRESS = {
        **_INGRESS_PROGRESS,
        **updates,
        "last_progress_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def ingress_progress_payload() -> dict[str, object]:
    return deepcopy(_INGRESS_PROGRESS)


def maintenance_quarantine_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    """Level-1 PAPER repair: isolate provider-rejected dynamic symbols."""
    for symbol in symbols:
        value = str(symbol).strip().upper()
        if value:
            _MAINTENANCE_QUARANTINED_SYMBOLS.add(value)
    return tuple(sorted(_MAINTENANCE_QUARANTINED_SYMBOLS))


def maintenance_quarantine_snapshot() -> tuple[str, ...]:
    return tuple(sorted(_MAINTENANCE_QUARANTINED_SYMBOLS))



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
    progress: dict[str, object]


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
            progress=ingress_progress_payload(),
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


def _quotes_by_asset(
    quotes: Sequence[object],
) -> dict[str, tuple[object, ...]]:
    """Partition a provider batch once so ingress does not rescan N quotes N times."""
    grouped: dict[str, list[object]] = {}
    for quote in quotes:
        asset_id = str(getattr(quote, "asset_id", "") or "").strip().lower()
        if not asset_id:
            raise ValueError("provider quote asset_id is required")
        grouped.setdefault(asset_id, []).append(quote)
    return {
        asset_id: tuple(rows)
        for asset_id, rows in sorted(grouped.items())
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
        if symbol.upper() in _MAINTENANCE_QUARANTINED_SYMBOLS:
            continue
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
    _publish_ingress_progress(
        cycle_state="running",
        phase="load_registry",
        cycle_started_at_utc=datetime.now(timezone.utc).isoformat(),
        eligible_asset_count=None,
        dynamic_chunk_count=None,
        completed_dynamic_chunk_count=0,
        processed_asset_count=0,
    )
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

        _publish_ingress_progress(
            phase="seed_quote",
            eligible_asset_count=len(CRYPTO_ASSETS) + len(dynamic_symbols),
        )

        # Keep the canonical seed lane isolated so a dynamic subscription problem
        # can never starve BTC/ETH market truth.
        seed_batch = await fetch_kraken_public_tickers(
            assets=CRYPTO_ASSETS,
            timeout_s=10.0,
        )
        all_quotes.extend(seed_batch.quotes)

        dynamic_assets = tuple(dynamic_symbols)
        dynamic_chunks = _chunks(
            dynamic_assets,
            configured_dynamic_ingress_batch_size(),
        )
        dynamic_worker_concurrency = configured_dynamic_ingress_worker_concurrency()
        dynamic_semaphore = asyncio.Semaphore(dynamic_worker_concurrency)
        completed_dynamic_chunks = 0
        _publish_ingress_progress(
            phase="dynamic_quote",
            dynamic_chunk_count=len(dynamic_chunks),
            completed_dynamic_chunk_count=0,
        )

        async def fetch_dynamic_chunk(
            chunk: tuple[str, ...],
        ) -> tuple[tuple[str, ...], object | None, str | None]:
            nonlocal completed_dynamic_chunks
            chunk_symbols = {asset: dynamic_symbols[asset] for asset in chunk}
            async with dynamic_semaphore:
                try:
                    batch = await fetch_kraken_public_tickers(
                        assets=chunk,
                        symbol_by_asset=chunk_symbols,
                        timeout_s=10.0,
                    )
                    return chunk, batch, None
                except Exception as exc:
                    return chunk, None, f"{type(exc).__name__}:{exc}"
                finally:
                    completed_dynamic_chunks += 1
                    _publish_ingress_progress(
                        completed_dynamic_chunk_count=completed_dynamic_chunks,
                    )

        # Dynamic provider I/O is bounded-concurrent. Eligibility remains the full
        # commissioned universe; worker capacity controls only simultaneous sockets.
        # One slow/rejected chunk cannot serialize every other catalog asset.
        dynamic_fetches = await asyncio.gather(
            *(fetch_dynamic_chunk(chunk) for chunk in dynamic_chunks)
        )
        for chunk, dynamic_batch, error in dynamic_fetches:
            if dynamic_batch is not None:
                all_quotes.extend(dynamic_batch.quotes)
            if error is not None:
                # A failed dynamic batch becomes explicit quote_missing attempts;
                # the seed lane and every other dynamic batch keep running.
                batch_errors.append({
                    "assets": list(chunk),
                    "error": error,
                })

        attempted_assets = CRYPTO_ASSETS + dynamic_assets
        quote_rows = tuple(all_quotes)
        quotes_by_asset = _quotes_by_asset(quote_rows)
        # Capture one post-I/O decision timestamp for the entire ingress cycle.
        # Every asset sees the same causal boundary. Each ingress call receives
        # only that asset's quote set rather than rescanning the full provider
        # payload for every asset.
        ingress_decision_at_utc = datetime.now(timezone.utc)
        _publish_ingress_progress(
            phase="persist_ingress",
            processed_asset_count=0,
        )

        def persist_ingress_cycle(sync_conn):
            cycle_results = []
            for asset_id in attempted_assets:
                cycle_results.append(
                    ingest_market_quotes(
                        sync_conn,
                        store,
                        asset_id=asset_id,
                        quotes=quotes_by_asset.get(asset_id, ()),
                        calendar_provider=None,
                        as_of_utc=ingress_decision_at_utc,
                    )
                )
            return tuple(cycle_results)

        async with engine.begin() as connection:
            ingress_results = await connection.run_sync(persist_ingress_cycle)

        _publish_ingress_progress(
            processed_asset_count=len(ingress_results),
        )
        for result in ingress_results:
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

    _publish_ingress_progress(
        cycle_state="complete",
        phase="idle",
        completed_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    return {
        "provider": "kraken_public",
        "status_system": seed_batch.status_system,
        "subscription_acknowledged": seed_batch.subscription_acknowledged,
        "seed_asset_count": len(CRYPTO_ASSETS),
        "dynamic_asset_count": len(dynamic_assets),
        "dynamic_batch_count": len(dynamic_chunks),
        "dynamic_batch_size": configured_dynamic_ingress_batch_size(),
        "dynamic_worker_concurrency": dynamic_worker_concurrency,
        "ingress_decision_at_utc": ingress_decision_at_utc.isoformat(),
        "quote_partition_asset_count": len(quotes_by_asset),
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


def configured_dynamic_ingress_worker_concurrency() -> int:
    raw = os.getenv(
        "AETHER_VNEXT_KRAKEN_INGRESS_WORKER_CONCURRENCY",
        "8",
    ).strip()
    value = int(raw)
    if value < 1 or value > 20:
        raise ValueError(
            "AETHER_VNEXT_KRAKEN_INGRESS_WORKER_CONCURRENCY must be between 1 and 20"
        )
    return value


def configured_ingress_enabled() -> bool:
    default = "true" if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "sandbox" else "false"
    raw = os.getenv("AETHER_VNEXT_KRAKEN_INGRESS_ENABLED", default).strip().lower()
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
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "sandbox":
        raise RuntimeError("vNext Kraken ingress requires sandbox environment")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("vNext Kraken ingress safety invariant failed")
    # Parse configuration before starting the task so a missing/invalid dedicated
    # database fails startup instead of falling back to legacy state.
    VNextDatabaseConfig.from_environment()


def status_payload(
    status: KrakenIngressSupervisorStatus,
) -> dict[str, object]:
    return asdict(status)
