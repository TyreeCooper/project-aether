"""Autonomous PAPER-only supervisor for the independent AETHER Consensus Tape."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from typing import Awaitable, Callable

from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.store import VNextStore
from aether_vnext.tape_policy import TapeAssetClass, TapeQuorumPolicy
from aether_vnext.tape_runtime import build_and_persist_tape_cycle
from aether_vnext.tape_sources import fetch_public_crypto_tape


UTC = timezone.utc
CycleRunner = Callable[[], Awaitable[dict[str, object]]]
CRYPTO_TAPE_ASSETS = {
    "btc": {"base_symbol": "BTC", "kraken_pair": "XBTUSD"},
    "eth": {"base_symbol": "ETH", "kraken_pair": "ETHUSD"},
}
_TAPE_PROGRESS: dict[str, object] = {
    "cycle_state": "idle",
    "phase": "idle",
    "cycle_started_at_utc": None,
    "last_progress_at_utc": None,
    "asset_count": len(CRYPTO_TAPE_ASSETS),
    "completed_asset_count": 0,
}


def _publish_progress(**updates: object) -> None:
    global _TAPE_PROGRESS
    _TAPE_PROGRESS = {
        **_TAPE_PROGRESS,
        **updates,
        "last_progress_at_utc": datetime.now(UTC).isoformat(),
    }


def tape_progress_payload() -> dict[str, object]:
    return deepcopy(_TAPE_PROGRESS)


@dataclass(frozen=True, slots=True)
class TapeSupervisorStatus:
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


class TapeSupervisor:
    def __init__(self, *, cycle_runner: CycleRunner, interval_seconds: float = 5.0):
        if interval_seconds < 2.0:
            raise ValueError("Tape interval_seconds must be >= 2")
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

    def status(self, *, enabled: bool = True) -> TapeSupervisorStatus:
        return TapeSupervisorStatus(
            enabled=enabled,
            running=self.running,
            paper_only=PAPER_ONLY,
            live_blocked=LIVE_BLOCKED,
            cycle_count=self._cycle_count,
            interval_seconds=self._interval_seconds,
            last_cycle_started_at_utc=None if self._last_started is None else self._last_started.isoformat(),
            last_cycle_finished_at_utc=None if self._last_finished is None else self._last_finished.isoformat(),
            last_error=self._last_error,
            last_result=self._last_result,
            progress=tape_progress_payload(),
        )

    async def start(self) -> None:
        if self.running:
            return
        if not PAPER_ONLY or not LIVE_BLOCKED:
            raise RuntimeError("Consensus Tape requires PAPER_ONLY/LIVE_BLOCKED")
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="aether-vnext-consensus-tape")

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
            self._last_started = datetime.now(UTC)
            try:
                self._last_result = dict(await self._cycle_runner())
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


def configured_tape_enabled() -> bool:
    default = "true" if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "sandbox" else "false"
    return os.getenv("AETHER_VNEXT_TAPE_ENABLED", default).strip().lower() in {"1", "true", "yes", "on"}


def configured_tape_interval_seconds() -> float:
    value = float(os.getenv("AETHER_VNEXT_TAPE_INTERVAL_SECONDS", "5").strip())
    if value < 2.0:
        raise ValueError("AETHER_VNEXT_TAPE_INTERVAL_SECONDS must be >= 2")
    return value


def configured_crypto_tape_policy() -> TapeQuorumPolicy:
    age_ms = int(os.getenv("AETHER_VNEXT_TAPE_CRYPTO_MAX_SOURCE_AGE_MS", "10000").strip())
    divergence_bps = float(os.getenv("AETHER_VNEXT_TAPE_CRYPTO_MAX_DIVERGENCE_BPS", "20").strip())
    return TapeQuorumPolicy(
        asset_class=TapeAssetClass.CRYPTO,
        required_quorum=3,
        degraded_quorum=2,
        max_sources=5,
        max_source_age_ms=age_ms,
        max_divergence_bps=divergence_bps,
    )


def validate_configured_tape_environment() -> None:
    if not configured_tape_enabled():
        return
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "sandbox":
        raise RuntimeError("Consensus Tape requires sandbox environment")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("Consensus Tape safety invariant failed")
    VNextDatabaseConfig.from_environment()
    configured_crypto_tape_policy()


async def run_configured_tape_cycle() -> dict[str, object]:
    validate_configured_tape_environment()
    policy = configured_crypto_tape_policy()
    _publish_progress(
        cycle_state="running",
        phase="fetch_sources",
        cycle_started_at_utc=datetime.now(UTC).isoformat(),
        completed_asset_count=0,
    )

    async def fetch_asset(asset_id: str, spec: dict[str, str]):
        result = await fetch_public_crypto_tape(
            asset_id=asset_id,
            base_symbol=spec["base_symbol"],
            kraken_pair=spec["kraken_pair"],
        )
        return asset_id, result

    fetched = await asyncio.gather(
        *(fetch_asset(asset_id, spec) for asset_id, spec in CRYPTO_TAPE_ASSETS.items())
    )
    as_of_utc = datetime.now(UTC)
    _publish_progress(phase="persist_consensus")

    store = VNextStore(schema="aether_vnext")
    rows: list[dict[str, object]] = []
    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            def persist(sync_conn):
                out = []
                for asset_id, fetch_result in fetched:
                    cycle = build_and_persist_tape_cycle(
                        sync_conn,
                        store,
                        asset_id=asset_id,
                        observations=fetch_result.observations,
                        source_failures=fetch_result.failures,
                        policy=policy,
                        as_of_utc=as_of_utc,
                    )
                    out.append({
                        "asset_id": asset_id,
                        "state": cycle.composite.state.value,
                        "confidence": cycle.composite.confidence.value,
                        "composite_id": cycle.composite.composite_id,
                        "composite_mark": cycle.composite.composite_mark,
                        "median_mark": cycle.composite.median_mark,
                        "source_count": cycle.composite.source_count,
                        "quorum_required": cycle.composite.quorum_required,
                        "accepted_source_ids": list(cycle.composite.accepted_source_ids),
                        "rejected_source_ids": list(cycle.composite.rejected_source_ids),
                        "source_failures": dict(cycle.source_failures),
                        "agreement_bps": cycle.composite.agreement_bps,
                        "max_source_age_ms": cycle.composite.max_source_age_ms,
                    })
                return out
            rows = await connection.run_sync(persist)

    _publish_progress(
        cycle_state="complete",
        phase="idle",
        completed_asset_count=len(rows),
        completed_at_utc=datetime.now(UTC).isoformat(),
    )
    return {
        "as_of_utc": as_of_utc.isoformat(),
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
        "policy": {
            "required_quorum": policy.required_quorum,
            "degraded_quorum": policy.degraded_quorum,
            "max_sources": policy.max_sources,
            "max_source_age_ms": policy.max_source_age_ms,
            "max_divergence_bps": policy.max_divergence_bps,
        },
        "assets": rows,
    }


def status_payload(status: TapeSupervisorStatus) -> dict[str, object]:
    return asdict(status)
