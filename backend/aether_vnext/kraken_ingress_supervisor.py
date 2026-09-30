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
from typing import Awaitable, Callable

from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.kraken_public import fetch_kraken_public_tickers
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


async def run_configured_kraken_ingress_cycle() -> dict[str, object]:
    """Fetch one public Kraken BBO batch and persist canonical ingress attempts."""
    batch = await fetch_kraken_public_tickers(
        assets=CRYPTO_ASSETS,
        timeout_s=10.0,
    )
    as_of_utc = datetime.now(timezone.utc)
    store = VNextStore(schema="aether_vnext")
    results: list[dict[str, object]] = []

    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            for asset_id in CRYPTO_ASSETS:
                result = await connection.run_sync(
                    lambda sync_conn, aid=asset_id: ingest_market_quotes(
                        sync_conn,
                        store,
                        asset_id=aid,
                        quotes=batch.quotes,
                        calendar_provider=None,
                        as_of_utc=as_of_utc,
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
        "status_system": batch.status_system,
        "subscription_acknowledged": batch.subscription_acknowledged,
        "asset_results": results,
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
    }


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
