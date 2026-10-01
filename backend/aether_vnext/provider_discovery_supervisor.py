"""Continuous provider-wide catalog discovery for AETHER vNext.

The supervisor is pre-Scout market intelligence only. It can discover/rank provider
universes and publish a Focus Pool, but it cannot create setups, tickets, fills, or
orders. Missing optional market-data credentials are reported explicitly.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from typing import Awaitable, Callable, Mapping

from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.kraken_catalog import fetch_kraken_discovery_universe
from aether_vnext.public_reference_discovery import (
    fetch_ibkr_us_equity_public_universe,
    fetch_ninjatrader_public_universe,
    fetch_tastyfx_public_universe,
)
from aether_vnext.provider_discovery import (
    DiscoveryInstrument,
    focus_payload,
    rank_provider_catalog,
)
from aether_vnext.provider_focus_handoff import (
    focus_handoff_rows,
    handoff_payload,
)


UTC = timezone.utc
PROVIDERS = ("Kraken", "tastyfx", "NinjaTrader", "IBKR")
CycleRunner = Callable[[], Awaitable[dict[str, object]]]
_LATEST_FOCUS_SNAPSHOT: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryStatus:
    enabled: bool
    running: bool
    paper_only: bool
    live_blocked: bool
    cycle_count: int
    interval_seconds: float
    initial_delay_seconds: float
    last_cycle_started_at_utc: str | None
    last_cycle_finished_at_utc: str | None
    last_error: str | None
    last_result: dict[str, object] | None


def _run_cycle_in_worker(cycle_runner: CycleRunner) -> dict[str, object]:
    """Run one async discovery cycle on a private event loop in a worker thread."""
    return dict(asyncio.run(cycle_runner()))


class ProviderDiscoverySupervisor:
    def __init__(
        self,
        *,
        cycle_runner: CycleRunner,
        interval_seconds: float = 300.0,
        initial_delay_seconds: float = 0.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be non-negative")
        self._cycle_runner = cycle_runner
        self._interval_seconds = float(interval_seconds)
        self._initial_delay_seconds = float(initial_delay_seconds)
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

    def status(self, *, enabled: bool = True) -> ProviderDiscoveryStatus:
        return ProviderDiscoveryStatus(
            enabled=enabled,
            running=self.running,
            paper_only=PAPER_ONLY,
            live_blocked=LIVE_BLOCKED,
            cycle_count=self._cycle_count,
            interval_seconds=self._interval_seconds,
            initial_delay_seconds=self._initial_delay_seconds,
            last_cycle_started_at_utc=None if self._last_started is None else self._last_started.isoformat(),
            last_cycle_finished_at_utc=None if self._last_finished is None else self._last_finished.isoformat(),
            last_error=self._last_error,
            last_result=self._last_result,
        )

    async def start(self) -> None:
        if self.running:
            return
        if not PAPER_ONLY or not LIVE_BLOCKED:
            raise RuntimeError("provider discovery requires PAPER_ONLY/LIVE_BLOCKED")
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="aether-vnext-provider-discovery")

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
        if self._initial_delay_seconds > 0:
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._initial_delay_seconds,
                )
            except TimeoutError:
                pass
            if self._stop.is_set():
                return

        while not self._stop.is_set():
            self._last_started = datetime.now(UTC)
            try:
                self._last_result = await asyncio.to_thread(
                    _run_cycle_in_worker,
                    self._cycle_runner,
                )
                self._last_error = None
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}:{exc}"
            finally:
                self._last_finished = datetime.now(UTC)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue


def build_provider_focus_snapshot(
    universes: Mapping[str, tuple[DiscoveryInstrument, ...]],
    *,
    provider_errors: Mapping[str, str] | None = None,
    as_of_utc: datetime,
) -> dict[str, object]:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    errors = dict(provider_errors or {})
    providers: dict[str, object] = {}
    focus_pool: list[dict[str, object]] = []

    for provider in PROVIDERS:
        rows = tuple(universes.get(provider, ()))
        if provider in errors:
            providers[provider] = {
                "provider": provider,
                "status": "unavailable",
                "reason": errors[provider],
                "catalog_count": len(rows),
                "eligible_count": 0,
                "focus_count": 0,
                "top25": [],
            }
            continue

        focus = rank_provider_catalog(rows, provider=provider, limit=25)
        payload = focus_payload(focus)
        payload["status"] = "online"
        payload["reason"] = None
        payload["catalog_mode"] = (
            "provider_native" if provider == "Kraken" else "public_reference_proxy"
        )
        payload["feed_classes"] = sorted({
            row.feed_class for row in rows if row.feed_class
        })
        payload["execution_binding_required"] = provider != "Kraken"
        providers[provider] = payload

        for row in payload["top25"]:
            focus_pool.append({
                **row,
                "provider": provider,
                "focus_key": provider + ":" + str(row["market_data_symbol"]),
                "pre_scout_only": True,
            })

    focus_pool.sort(key=lambda row: (str(row["provider"]), int(row["rank"])))
    handoff = focus_handoff_rows(focus_pool)
    handoff_rows = handoff_payload(handoff)
    return {
        "as_of_utc": as_of_utc.astimezone(UTC).isoformat(),
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
        "forced_entries_enabled": False,
        "natural_setup_only": True,
        "stage": "PRE_SCOUT_FOCUS",
        "providers": providers,
        "focus_pool": focus_pool,
        "focus_count": len(focus_pool),
        "scout_handoff": handoff_rows,
        "scout_ready_count": sum(
            1 for row in handoff_rows if row["state"] == "SCOUT_READY"
        ),
        "discovery_only_count": sum(
            1 for row in handoff_rows if row["state"] == "DISCOVERY_ONLY"
        ),
        "provider_count": len(PROVIDERS),
        "online_provider_count": sum(
            1 for row in providers.values()
            if isinstance(row, Mapping) and row.get("status") == "online"
        ),
        "trading_authority": False,
    }


def current_deep_trade_focus_asset_ids() -> frozenset[str] | None:
    """Return latest safe deep-runtime focus IDs, or None before first cycle."""
    snapshot = _LATEST_FOCUS_SNAPSHOT
    if snapshot is None:
        return None
    handoff = snapshot.get("scout_handoff")
    if not isinstance(handoff, list):
        return frozenset()
    return frozenset(
        str(row["canonical_asset_id"])
        for row in handoff
        if (
            isinstance(row, Mapping)
            and row.get("state") == "SCOUT_READY"
            and row.get("canonical_asset_id")
        )
    )


async def run_configured_provider_discovery_cycle() -> dict[str, object]:
    global _LATEST_FOCUS_SNAPSHOT
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("provider discovery safety invariant failed")

    universes: dict[str, tuple[DiscoveryInstrument, ...]] = {}
    errors: dict[str, str] = {}

    providers = (
        ("Kraken", fetch_kraken_discovery_universe),
        ("tastyfx", fetch_tastyfx_public_universe),
        ("NinjaTrader", fetch_ninjatrader_public_universe),
        ("IBKR", fetch_ibkr_us_equity_public_universe),
    )
    # Resource-bound by design: one provider universe at a time. This avoids
    # multiplying network buffers and parser memory on the small nonprod worker.
    for provider, fetcher in providers:
        try:
            universes[provider] = tuple(await fetcher())
        except Exception as exc:
            errors[provider] = f"{type(exc).__name__}:{exc}"

    snapshot = build_provider_focus_snapshot(
        universes,
        provider_errors=errors,
        as_of_utc=datetime.now(UTC),
    )
    _LATEST_FOCUS_SNAPSHOT = dict(snapshot)
    return snapshot


def configured_discovery_enabled() -> bool:
    default = (
        "true"
        if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "burnin"
        else "false"
    )
    raw = os.getenv("AETHER_VNEXT_PROVIDER_DISCOVERY_ENABLED", default).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def configured_discovery_interval_seconds() -> float:
    raw = os.getenv("AETHER_VNEXT_PROVIDER_DISCOVERY_INTERVAL_SECONDS", "300").strip()
    value = float(raw)
    if value < 60.0:
        raise ValueError("AETHER_VNEXT_PROVIDER_DISCOVERY_INTERVAL_SECONDS must be >= 60")
    return value


def configured_discovery_initial_delay_seconds() -> float:
    raw = os.getenv(
        "AETHER_VNEXT_PROVIDER_DISCOVERY_INITIAL_DELAY_SECONDS",
        "15",
    ).strip()
    value = float(raw)
    if value < 0.0 or value > 120.0:
        raise ValueError(
            "AETHER_VNEXT_PROVIDER_DISCOVERY_INITIAL_DELAY_SECONDS must be between 0 and 120"
        )
    return value


def validate_configured_discovery_environment() -> None:
    if not configured_discovery_enabled():
        return
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "burnin":
        raise RuntimeError("provider discovery may only run in burnin")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("provider discovery safety invariant failed")


def status_payload(status: ProviderDiscoveryStatus) -> dict[str, object]:
    return asdict(status)
