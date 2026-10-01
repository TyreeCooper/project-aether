"""Autonomous BTC/ETH PAPER strategy supervisor for the vNext prototype.

The supervisor:
- refreshes only completed Kraken 1h/daily bars into prototype_market_bars;
- rebuilds source-bound features from the bootstrapped ledger;
- manages existing OPEN trades before considering new entries;
- routes entries through Scout -> Sniper -> Risk -> Clerk -> Portfolio -> PAPER;
- routes exits through Exit -> Portfolio -> PAPER CLOSE;
- never retries the same completed-bar trade after that setup has already opened
  and closed;
- never creates Phase-18 evidence or live orders.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from typing import Awaitable, Callable

import sqlalchemy as sa

from aether_vnext.coinbase_prototype_history import COINBASE_SOURCE_ID
from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.dynamic_products import project_kraken_spot_product
from aether_vnext.freeze import CONFIGURATION_HASH, LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.prototype_crypto_entry_plan import build_prototype_crypto_entry_plan
from aether_vnext.prototype_crypto_entry_runtime import advance_prototype_crypto_entry
from aether_vnext.prototype_crypto_exit_runtime import advance_prototype_crypto_exit
from aether_vnext.prototype_forward_paper_evidence import (
    count_prototype_no_setup_observations,
    persist_prototype_no_setup_observation,
)
from aether_vnext.prototype_crypto_warmup import assemble_prototype_crypto_warmup
from aether_vnext.prototype_history_sources import (
    KRAKEN_DAILY_SOURCE_ID,
    fetch_kraken_completed_daily,
    fetch_kraken_completed_hourly,
)
from aether_vnext.prototype_market_history import (
    load_prototype_market_bars,
    persist_prototype_market_bars,
)
from aether_vnext.provider_discovery_supervisor import (
    current_deep_trade_focus_asset_ids,
    current_provider_focus_snapshot,
)
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.store import VNextStore


UTC = timezone.utc
EXPECTED_EPOCH = "aether-prototype-new-system-test-001"
ASSETS = ("btc", "eth")
CycleRunner = Callable[[], Awaitable[dict[str, object]]]


@dataclass(frozen=True, slots=True)
class PrototypeStrategySupervisorStatus:
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


class PrototypeStrategySupervisor:
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

    def status(self, *, enabled: bool = True) -> PrototypeStrategySupervisorStatus:
        return PrototypeStrategySupervisorStatus(
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
            raise RuntimeError("prototype strategy requires PAPER_ONLY/LIVE_BLOCKED")
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="aether-vnext-prototype-strategy",
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
            self._last_started = datetime.now(UTC)
            try:
                result = await self._cycle_runner()
                self._last_result = dict(result)
                self._last_error = None
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}:{exc}"
            finally:
                self._last_finished = datetime.now(UTC)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue


def _latest_observation(
    sync_conn,
    store: VNextStore,
    *,
    asset_id: str,
):
    attempt = store.latest_market_ingress_attempt(sync_conn, asset_id=asset_id)
    if attempt is None or not bool(attempt["executable"]):
        return None
    observation_id = attempt.get("observation_id")
    if not observation_id:
        return None
    return store.load_market_observation(
        sync_conn,
        observation_id=str(observation_id),
    )


def _entry_focus_block(
    *,
    asset_id: str,
    focused_asset_ids: frozenset[str] | None,
    assets_open_at_start: set[str],
) -> dict[str, object] | None:
    """Compatibility hook: provider focus is priority telemetry, not a trade veto.

    Commissioned strategies must still pass their normal market, setup, Risk, Clerk,
    Portfolio, and PAPER execution gates. A missing or out-of-focus provider ranking
    alone must never suppress an otherwise valid strategy entry.
    """
    _ = (asset_id, focused_asset_ids, assets_open_at_start)
    return None


def _setup_already_completed(
    sync_conn,
    store: VNextStore,
    *,
    setup_id: str,
) -> bool:
    """Return True once a setup has ever produced an OpenTrade.

    OpenTrade is durable execution evidence and remains present after FLAT;
    ClosedTrade references it by trade_id but intentionally does not duplicate
    setup_id. Therefore OpenTrade alone is the canonical no-reentry lookup.
    """
    open_trades = store.tables["open_trades"]
    return sync_conn.execute(
        sa.select(open_trades.c.trade_id)
        .where(open_trades.c.setup_id == setup_id)
        .limit(1)
    ).first() is not None


def _sync_dynamic_kraken_products(
    sync_conn,
    store: VNextStore,
    *,
    focus_snapshot: dict[str, object] | None,
    as_of_utc: datetime,
) -> dict[str, object]:
    """Persist source-complete Kraken products using the existing provider policy."""
    if focus_snapshot is None:
        return {
            "status": "waiting_for_discovery",
            "received": 0,
            "persisted": 0,
            "requirements": {},
        }

    runtime = store.load_runtime_registry_binding(
        sync_conn,
        asset_id="btc",
    )
    if runtime is None:
        return {
            "status": "provider_policy_missing",
            "received": 0,
            "persisted": 0,
            "requirements": {"provider_policy_missing": 1},
        }
    binding = runtime["binding"]
    source_id = str(binding.primary_market_source_id or "").strip() or None
    stale_threshold_ms = binding.stale_threshold_ms

    providers = focus_snapshot.get("providers") or {}
    kraken = providers.get("Kraken") if isinstance(providers, dict) else None
    rows = (
        kraken.get("top100") or []
        if isinstance(kraken, dict)
        else []
    )

    persisted = 0
    requirement_counts: dict[str, int] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        focus_row = {**raw, "provider": "Kraken"}
        projection = project_kraken_spot_product(
            focus_row,
            primary_market_source_id=source_id,
            stale_threshold_ms=stale_threshold_ms,
        )
        if projection.product is None:
            for requirement in projection.requirements:
                requirement_counts[requirement] = (
                    requirement_counts.get(requirement, 0) + 1
                )
            continue
        if projection.asset_id in SEED_REGISTRY:
            # Frozen BTC/ETH continue using their canonical seed binding path.
            continue
        store.upsert_dynamic_product_state(
            sync_conn,
            projection.product,
            source_ref=(
                str(raw.get("source") or "kraken_public")
                + ":"
                + str(raw.get("execution_symbol") or raw.get("symbol") or "")
            ),
            registry_version="dynamic-kraken-v1",
            configuration_hash=CONFIGURATION_HASH,
            updated_at_utc=as_of_utc,
        )
        persisted += 1

    return {
        "status": "synced",
        "received": len(rows),
        "persisted": persisted,
        "requirements": dict(sorted(requirement_counts.items())),
    }


async def run_configured_prototype_strategy_cycle() -> dict[str, object]:
    """Run one crash-safe prototype strategy pass."""
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype strategy safety invariant failed")

    as_of_utc = datetime.now(UTC)
    focused_asset_ids = current_deep_trade_focus_asset_ids()
    focus_snapshot = current_provider_focus_snapshot()
    fetched_hourly = {}
    fetched_daily = {}
    for asset_id in ASSETS:
        fetched_hourly[asset_id] = await fetch_kraken_completed_hourly(
            asset_id=asset_id,
            end_at_utc=as_of_utc,
        )
        fetched_daily[asset_id] = await fetch_kraken_completed_daily(
            asset_id=asset_id,
            end_at_utc=as_of_utc,
        )

    store = VNextStore(schema="aether_vnext")
    result: dict[str, object] = {
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
        "phase18_evidence": False,
        "as_of_utc": as_of_utc.isoformat(),
        "provider_focus_available": focused_asset_ids is not None,
        "deep_trade_focus_asset_ids": (
            None if focused_asset_ids is None else sorted(focused_asset_ids)
        ),
        "assets": {},
    }

    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            def cycle(sync_conn):
                epoch = store.current_paper_test_epoch(sync_conn)
                if epoch is None or str(epoch["epoch_id"]) != EXPECTED_EPOCH:
                    raise RuntimeError("prototype paper epoch is not the expected fresh epoch")
                if not bool(epoch["paper_only"]) or not bool(epoch["live_blocked"]):
                    raise RuntimeError("prototype paper epoch safety flags changed")

                result["dynamic_product_registry"] = _sync_dynamic_kraken_products(
                    sync_conn,
                    store,
                    focus_snapshot=focus_snapshot,
                    as_of_utc=as_of_utc,
                )

                inserted = 0
                for asset_id in ASSETS:
                    inserted += persist_prototype_market_bars(
                        sync_conn,
                        store,
                        tuple((*fetched_hourly[asset_id], *fetched_daily[asset_id])),
                        ingested_at_utc=as_of_utc,
                    )

                observations = {
                    asset_id: observation
                    for asset_id in ASSETS
                    if (
                        observation := _latest_observation(
                            sync_conn,
                            store,
                            asset_id=asset_id,
                        )
                    ) is not None
                }

                # Network/history work can take seconds. Decision time must be
                # captured after the current market observations are loaded,
                # never before them.
                decision_at_utc = datetime.now(UTC)
                for observation in observations.values():
                    market_times = (
                        observation.exchange_ts,
                        observation.received_ts,
                    )
                    if any(
                        stamp is not None and stamp > decision_at_utc
                        for stamp in market_times
                    ):
                        raise ValueError(
                            "market timestamp cannot be after decision time"
                        )
                result["decision_at_utc"] = decision_at_utc.isoformat()

                open_table = store.tables["open_trades"]
                open_rows = tuple(
                    sync_conn.execute(
                        sa.select(open_table).where(open_table.c.asset_id.in_(ASSETS))
                    ).mappings()
                )
                assets_open_at_start = {str(row["asset_id"]) for row in open_rows}
                exit_results: dict[str, object] = {}

                for trade in open_rows:
                    asset_id = str(trade["asset_id"])
                    observation = observations.get(asset_id)
                    if observation is None:
                        exit_results[asset_id] = {
                            "stage": "OPEN",
                            "reason": "current_executable_observation_missing",
                            "trade_id": str(trade["trade_id"]),
                        }
                        continue
                    latest_bar = fetched_hourly[asset_id][-1] if fetched_hourly[asset_id] else None
                    advanced = advance_prototype_crypto_exit(
                        sync_conn,
                        store,
                        trade_id=str(trade["trade_id"]),
                        current_observation=observation,
                        latest_completed_hourly_bar=latest_bar,
                        as_of_utc=decision_at_utc,
                    )
                    exit_results[asset_id] = asdict(advanced)

                asset_results: dict[str, object] = {}
                for asset_id in ASSETS:
                    observation = observations.get(asset_id)
                    if observation is None:
                        asset_results[asset_id] = {
                            "stage": "NO_DECISION",
                            "reason": "current_executable_observation_missing",
                        }
                        continue

                    if asset_id in assets_open_at_start:
                        asset_results[asset_id] = {
                            "stage": "MANAGE_OPEN",
                            "reason": "trade_was_open_at_cycle_start",
                            "focus_selected": (
                                None
                                if focused_asset_ids is None
                                else asset_id in focused_asset_ids
                            ),
                        }
                        continue

                    focus_selected = (
                        None
                        if focused_asset_ids is None
                        else asset_id in focused_asset_ids
                    )
                    focus_block = _entry_focus_block(
                        asset_id=asset_id,
                        focused_asset_ids=focused_asset_ids,
                        assets_open_at_start=assets_open_at_start,
                    )
                    if focus_block is not None:
                        asset_results[asset_id] = focus_block
                        continue

                    hourly = load_prototype_market_bars(
                        sync_conn,
                        store,
                        asset_id=asset_id,
                        interval_seconds=3600,
                        end_at_utc=decision_at_utc,
                    )
                    asset_daily = load_prototype_market_bars(
                        sync_conn,
                        store,
                        asset_id=asset_id,
                        interval_seconds=86400,
                        end_at_utc=decision_at_utc,
                    )
                    btc_daily = load_prototype_market_bars(
                        sync_conn,
                        store,
                        asset_id="btc",
                        interval_seconds=86400,
                        end_at_utc=decision_at_utc,
                    )
                    warmup = assemble_prototype_crypto_warmup(
                        asset_id=asset_id,
                        coinbase_hourly=tuple(
                            row for row in hourly if row.source_id == COINBASE_SOURCE_ID
                        ),
                        kraken_hourly=tuple(
                            row for row in hourly if row.source_id == KRAKEN_DAILY_SOURCE_ID
                        ),
                        asset_kraken_daily=tuple(
                            row for row in asset_daily if row.source_id == KRAKEN_DAILY_SOURCE_ID
                        ),
                        btc_kraken_daily=tuple(
                            row for row in btc_daily if row.source_id == KRAKEN_DAILY_SOURCE_ID
                        ),
                        as_of_utc=decision_at_utc,
                    )
                    feature = warmup.feature_snapshot
                    plan = build_prototype_crypto_entry_plan(
                        feature=feature,
                        current_observation=observation,
                        as_of_utc=decision_at_utc,
                    )

                    if _setup_already_completed(
                        sync_conn,
                        store,
                        setup_id=plan.ids.setup_id,
                    ):
                        asset_results[asset_id] = {
                            "stage": "NO_REENTRY",
                            "reason": "completed_bar_setup_already_traded",
                            "trigger_close_utc": feature.trigger_close_utc.isoformat(),
                            "watch_eligible": feature.watch_eligible,
                        }
                        continue

                    advanced = advance_prototype_crypto_entry(
                        sync_conn,
                        store,
                        plan=plan,
                        completed_bar=warmup.hourly_bars[-1],
                        current_observation=observation,
                        current_observations=observations,
                        as_of_utc=decision_at_utc,
                    )
                    asset_result = {
                        **asdict(advanced),
                        "focus_selected": focus_selected,
                        "watch_eligible": feature.watch_eligible,
                        "volatility_percentile": feature.volatility.percentile,
                    }
                    if advanced.stage == "NO_SETUP":
                        observation_new = persist_prototype_no_setup_observation(
                            sync_conn,
                            store,
                            paper_epoch_id=EXPECTED_EPOCH,
                            asset_id=asset_id,
                            trigger_close_utc=feature.trigger_close_utc,
                            evaluated_at_utc=decision_at_utc,
                            market_observation_id=observation.observation_id,
                            reason=advanced.reason,
                            watch_eligible=feature.watch_eligible,
                            volatility_percentile=feature.volatility.percentile,
                            setup_id=advanced.setup_id,
                            ticket_id=advanced.ticket_id,
                            order_intent_id=advanced.order_intent_id,
                        )
                        asset_result["forward_paper_observation_recorded"] = True
                        asset_result["forward_paper_observation_new"] = observation_new
                    asset_results[asset_id] = asset_result

                result["inserted_market_bars"] = inserted
                result["current_observation_asset_ids"] = sorted(observations)
                result["open_assets_at_cycle_start"] = sorted(assets_open_at_start)
                result["exit_results"] = exit_results
                result["assets"] = asset_results
                result["paper_epoch_id"] = EXPECTED_EPOCH
                result["forward_paper_observation_count"] = (
                    count_prototype_no_setup_observations(
                        sync_conn,
                        store,
                        paper_epoch_id=EXPECTED_EPOCH,
                    )
                )

            await connection.run_sync(cycle)

    return result


def configured_strategy_enabled() -> bool:
    raw = os.getenv("AETHER_VNEXT_PROTOTYPE_TRADING_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def configured_strategy_interval_seconds() -> float:
    raw = os.getenv("AETHER_VNEXT_PROTOTYPE_TRADING_INTERVAL_SECONDS", "15").strip()
    value = float(raw)
    if value < 5.0:
        raise ValueError("AETHER_VNEXT_PROTOTYPE_TRADING_INTERVAL_SECONDS must be >= 5")
    return value


def validate_configured_strategy_environment() -> None:
    if not configured_strategy_enabled():
        return
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "burnin":
        raise RuntimeError("prototype strategy may only run in burnin")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype strategy safety invariant failed")
    VNextDatabaseConfig.from_environment()


def status_payload(
    status: PrototypeStrategySupervisorStatus,
) -> dict[str, object]:
    return asdict(status)
