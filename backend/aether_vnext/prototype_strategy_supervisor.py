"""Autonomous PAPER strategy supervisor for the vNext sandbox.

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
from typing import Awaitable, Callable, Mapping, Sequence

import sqlalchemy as sa

from aether_vnext.coinbase_prototype_history import (
    COINBASE_SOURCE_ID,
    fetch_coinbase_hourly_history,
    fetch_coinbase_public_products,
)
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
    PrototypeMarketBar,
    load_prototype_market_bars,
    persist_prototype_market_bars,
)
from aether_vnext.provider_discovery_supervisor import (
    current_deep_trade_focus_asset_ids,
    current_provider_focus_snapshot,
)
from aether_vnext.registry import ProductRegistryRow, SEED_REGISTRY
from aether_vnext.runtime_product_policy import runtime_playbook_for_product
from aether_vnext.store import VNextStore


UTC = timezone.utc
SANDBOX_SESSION_ID = "aether-sandbox"
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


@dataclass(frozen=True, slots=True)
class DynamicStrategyHistory:
    asset_id: str
    coinbase_product: str | None
    coinbase_hourly: tuple[PrototypeMarketBar, ...]
    kraken_hourly: tuple[PrototypeMarketBar, ...]
    kraken_daily: tuple[PrototypeMarketBar, ...]
    error: str | None


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


def _partition_observations_for_decision_time(
    observations: Mapping[str, object],
    *,
    decision_at_utc: datetime,
) -> tuple[dict[str, object], dict[str, str], tuple[str, ...]]:
    """Keep one clock-skewed market row from aborting the entire PAPER funnel.

    received_ts is the local causal boundary: a locally received observation cannot
    be used before its receive time. exchange_ts belongs to the remote venue clock,
    so positive exchange-clock skew is retained as telemetry instead of becoming a
    cycle-wide fatal error.
    """
    if decision_at_utc.tzinfo is None:
        raise ValueError("decision_at_utc must be timezone-aware")

    accepted: dict[str, object] = {}
    rejected: dict[str, str] = {}
    exchange_clock_ahead: list[str] = []
    for raw_asset_id, observation in observations.items():
        asset_id = str(raw_asset_id).strip().lower()
        received_ts = getattr(observation, "received_ts", None)
        exchange_ts = getattr(observation, "exchange_ts", None)
        if received_ts is None or received_ts.tzinfo is None:
            rejected[asset_id] = "received_timestamp_missing_or_naive"
            continue
        if received_ts > decision_at_utc:
            rejected[asset_id] = "received_timestamp_after_decision_time"
            continue
        if exchange_ts is not None:
            if exchange_ts.tzinfo is None:
                rejected[asset_id] = "exchange_timestamp_naive"
                continue
            if exchange_ts > decision_at_utc:
                exchange_clock_ahead.append(asset_id)
        accepted[asset_id] = observation

    return (
        accepted,
        rejected,
        tuple(sorted(exchange_clock_ahead)),
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
        (kraken.get("eligible_catalog") or kraken.get("top100") or [])
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


def configured_dynamic_strategy_scan_batch_size() -> int:
    raw = os.getenv(
        "AETHER_VNEXT_DYNAMIC_STRATEGY_SCAN_BATCH_SIZE",
        "4",
    ).strip()
    value = int(raw)
    if value < 1 or value > 20:
        raise ValueError(
            "AETHER_VNEXT_DYNAMIC_STRATEGY_SCAN_BATCH_SIZE must be between 1 and 20"
        )
    return value


def _current_dynamic_kraken_products(
    states: Sequence[Mapping[str, object]],
    *,
    focus_snapshot: Mapping[str, object] | None,
    include_asset_ids: Sequence[str] = (),
) -> tuple[ProductRegistryRow, ...]:
    """Return every commissioned compatible Kraken product; focus never gates it."""
    _ = (focus_snapshot, include_asset_ids)
    products: list[ProductRegistryRow] = []
    for state in states:
        product = state.get("product")
        if not isinstance(product, ProductRegistryRow):
            continue
        asset_id = str(product.asset_id).strip().lower()
        if asset_id in SEED_REGISTRY:
            continue
        if not str(product.broker_symbol or "").strip():
            continue
        try:
            runtime_playbook_for_product(
                product,
                playbook_id="pb_crypto_swing_v1_2",
            )
        except RuntimeError:
            continue
        products.append(product)
    return tuple(sorted(products, key=lambda row: row.asset_id))


def _focus_priority_asset_ids(
    products: Sequence[ProductRegistryRow],
    *,
    focus_snapshot: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Map Kraken Top-100 attention rank to commissioned asset IDs only."""
    providers = (
        focus_snapshot.get("providers")
        if isinstance(focus_snapshot, Mapping)
        else None
    )
    kraken = providers.get("Kraken") if isinstance(providers, Mapping) else None
    rows = kraken.get("top100") if isinstance(kraken, Mapping) else None
    by_symbol = {
        str(row.broker_symbol or "").strip(): row.asset_id
        for row in products
        if str(row.broker_symbol or "").strip()
    }
    return tuple(
        by_symbol[symbol]
        for raw in (rows or ())
        if isinstance(raw, Mapping)
        and (symbol := str(raw.get("execution_symbol") or "").strip()) in by_symbol
    )


def _rotating_dynamic_strategy_batch(
    products: Sequence[ProductRegistryRow],
    *,
    as_of_utc: datetime,
    interval_seconds: float,
    batch_size: int,
    priority_asset_ids: Sequence[str] = (),
    attention_asset_ids: Sequence[str] = (),
) -> tuple[ProductRegistryRow, ...]:
    """Choose a bounded slice: OPEN always wins; attention ranks accelerate, never gate."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    rows = tuple(sorted(products, key=lambda row: row.asset_id))
    if not rows:
        return ()

    by_id = {row.asset_id: row for row in rows}
    open_priority = tuple(
        by_id[asset_id]
        for asset_id in dict.fromkeys(
            str(value).strip().lower() for value in priority_asset_ids
        )
        if asset_id in by_id
    )
    open_ids = {row.asset_id for row in open_priority}
    remaining = tuple(row for row in rows if row.asset_id not in open_ids)
    capacity = max(batch_size - len(open_priority), 0)
    if capacity == 0 or not remaining:
        return open_priority

    attention_ids = tuple(
        asset_id
        for asset_id in dict.fromkeys(
            str(value).strip().lower() for value in attention_asset_ids
        )
        if asset_id in by_id and asset_id not in open_ids
    )
    attention_set = set(attention_ids)
    attention = tuple(
        by_id[asset_id]
        for asset_id in attention_ids
        if asset_id in by_id
    )
    background = tuple(
        row for row in remaining if row.asset_id not in attention_set
    )
    slot = int(as_of_utc.timestamp() // interval_seconds)

    def rotate(group: Sequence[ProductRegistryRow], count: int, salt: int) -> tuple[ProductRegistryRow, ...]:
        rows_ = tuple(group)
        if count <= 0 or not rows_:
            return ()
        take = min(count, len(rows_))
        start = ((slot + salt) * max(take, 1)) % len(rows_)
        return tuple(
            rows_[(start + offset) % len(rows_)]
            for offset in range(take)
        )

    if attention and background and capacity == 1:
        # One-slot configurations still prospect the full universe instead of
        # permanently starving non-Top-100 products.
        selected = (
            rotate(attention, 1, 0)
            if slot % 2 == 0
            else rotate(background, 1, 1)
        )
        return (*open_priority, *selected)

    if attention and background:
        attention_capacity = min(
            len(attention),
            max(1, (capacity * 3 + 3) // 4),
        )
        background_capacity = max(1, capacity - attention_capacity)
        if attention_capacity + background_capacity > capacity:
            attention_capacity = max(0, capacity - background_capacity)
        selected_attention = rotate(attention, attention_capacity, 0)
        selected_background = rotate(background, background_capacity, 1)
        selected = (*selected_attention, *selected_background)
        if len(selected) < capacity:
            used = {row.asset_id for row in selected}
            spill = tuple(row for row in remaining if row.asset_id not in used)
            selected = (*selected, *rotate(spill, capacity - len(selected), 2))
        return (*open_priority, *selected)

    selected = rotate(attention or background or remaining, capacity, 0)
    return (*open_priority, *selected)


def _coinbase_warmup_cached(
    rows: Sequence[PrototypeMarketBar],
    *,
    minimum_bars: int = 2200,
) -> bool:
    if minimum_bars < 1:
        raise ValueError("minimum_bars must be positive")
    return sum(
        1 for row in rows
        if row.source_id == COINBASE_SOURCE_ID
    ) >= minimum_bars


async def _fetch_dynamic_strategy_history(
    product: ProductRegistryRow,
    *,
    coinbase_products: Mapping[tuple[str, str], str],
    end_at_utc: datetime,
    fetch_coinbase_warmup: bool,
) -> DynamicStrategyHistory:
    """Fetch one dynamic asset's history without allowing it to fail the cycle."""
    asset_id = str(product.asset_id).strip().lower()
    base = str(product.base_currency or "").strip().upper()
    quote = str(product.quote_currency or "").strip().upper()
    kraken_pair = str(product.broker_symbol or "").strip().upper()

    if not base or quote != "USD" or not kraken_pair:
        return DynamicStrategyHistory(
            asset_id=asset_id,
            coinbase_product=None,
            coinbase_hourly=(),
            kraken_hourly=(),
            kraken_daily=(),
            error="product_history_identity_incomplete",
        )

    coinbase_product = coinbase_products.get((base, "USD"))
    if fetch_coinbase_warmup and not coinbase_product:
        return DynamicStrategyHistory(
            asset_id=asset_id,
            coinbase_product=None,
            coinbase_hourly=(),
            kraken_hourly=(),
            kraken_daily=(),
            error="coinbase_warmup_product_unavailable",
        )

    try:
        if fetch_coinbase_warmup:
            coinbase_hourly, kraken_hourly, kraken_daily = await asyncio.gather(
                fetch_coinbase_hourly_history(
                    asset_id=asset_id,
                    coinbase_product=coinbase_product,
                    end_at_utc=end_at_utc,
                    minimum_bars=2200,
                ),
                fetch_kraken_completed_hourly(
                    asset_id=asset_id,
                    kraken_pair=kraken_pair,
                    end_at_utc=end_at_utc,
                ),
                fetch_kraken_completed_daily(
                    asset_id=asset_id,
                    kraken_pair=kraken_pair,
                    end_at_utc=end_at_utc,
                ),
            )
        else:
            kraken_hourly, kraken_daily = await asyncio.gather(
                fetch_kraken_completed_hourly(
                    asset_id=asset_id,
                    kraken_pair=kraken_pair,
                    end_at_utc=end_at_utc,
                ),
                fetch_kraken_completed_daily(
                    asset_id=asset_id,
                    kraken_pair=kraken_pair,
                    end_at_utc=end_at_utc,
                ),
            )
            coinbase_hourly = ()
    except Exception as exc:
        return DynamicStrategyHistory(
            asset_id=asset_id,
            coinbase_product=coinbase_product,
            coinbase_hourly=(),
            kraken_hourly=(),
            kraken_daily=(),
            error=f"history_fetch_error:{type(exc).__name__}:{exc}",
        )

    return DynamicStrategyHistory(
        asset_id=asset_id,
        coinbase_product=coinbase_product,
        coinbase_hourly=tuple(coinbase_hourly),
        kraken_hourly=tuple(kraken_hourly),
        kraken_daily=tuple(kraken_daily),
        error=None,
    )


def _stage_count(
    rows: Mapping[str, Mapping[str, object]],
    *stages: str,
) -> int:
    wanted = set(stages)
    return sum(1 for row in rows.values() if str(row.get("stage")) in wanted)


async def run_configured_prototype_strategy_cycle() -> dict[str, object]:
    """Run one crash-safe seed + dynamic Kraken PAPER strategy pass."""
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("sandbox strategy safety invariant failed")

    as_of_utc = datetime.now(UTC)
    focused_asset_ids = current_deep_trade_focus_asset_ids()
    focus_snapshot = current_provider_focus_snapshot()
    store = VNextStore(schema="aether_vnext")

    # Seed history remains independent so dynamic-source faults cannot starve BTC/ETH.
    fetched_hourly: dict[str, tuple[PrototypeMarketBar, ...]] = {}
    fetched_daily: dict[str, tuple[PrototypeMarketBar, ...]] = {}
    for asset_id in ASSETS:
        fetched_hourly[asset_id] = await fetch_kraken_completed_hourly(
            asset_id=asset_id,
            end_at_utc=as_of_utc,
        )
        fetched_daily[asset_id] = await fetch_kraken_completed_daily(
            asset_id=asset_id,
            end_at_utc=as_of_utc,
        )

    result: dict[str, object] = {
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
        "as_of_utc": as_of_utc.isoformat(),
        "provider_focus_available": focused_asset_ids is not None,
        "deep_trade_focus_asset_ids": (
            None if focused_asset_ids is None else sorted(focused_asset_ids)
        ),
        "assets": {},
        "dynamic_assets": {},
    }

    async with open_vnext_engine() as engine:
        # First transaction: persist current provider truth and plan this roaming slice.
        async with engine.begin() as connection:
            def prepare(sync_conn):
                # Sandbox execution is continuous. It is not gated by a named test epoch.
                registry_status = _sync_dynamic_kraken_products(
                    sync_conn,
                    store,
                    focus_snapshot=focus_snapshot,
                    as_of_utc=as_of_utc,
                )
                states = store.list_dynamic_product_states(sync_conn)

                open_table = store.tables["open_trades"]
                all_open_rows = tuple(
                    sync_conn.execute(sa.select(open_table)).mappings()
                )
                dynamic_state_ids = {
                    str(state["product"].asset_id).strip().lower()
                    for state in states
                    if isinstance(state.get("product"), ProductRegistryRow)
                }
                dynamic_open_ids = tuple(
                    str(row["asset_id"]).strip().lower()
                    for row in all_open_rows
                    if str(row["asset_id"]).strip().lower() in dynamic_state_ids
                )
                products = _current_dynamic_kraken_products(
                    states,
                    focus_snapshot=focus_snapshot,
                    include_asset_ids=dynamic_open_ids,
                )
                attention_ids = _focus_priority_asset_ids(
                    products,
                    focus_snapshot=focus_snapshot,
                )
                batch = _rotating_dynamic_strategy_batch(
                    products,
                    as_of_utc=as_of_utc,
                    interval_seconds=configured_strategy_interval_seconds(),
                    batch_size=configured_dynamic_strategy_scan_batch_size(),
                    priority_asset_ids=dynamic_open_ids,
                    attention_asset_ids=attention_ids,
                )
                market_ready = {
                    product.asset_id: _latest_observation(
                        sync_conn,
                        store,
                        asset_id=product.asset_id,
                    )
                    for product in batch
                }
                warmup_cached = {}
                for product in batch:
                    rows = load_prototype_market_bars(
                        sync_conn,
                        store,
                        asset_id=product.asset_id,
                        interval_seconds=3600,
                        end_at_utc=as_of_utc,
                    )
                    warmup_cached[product.asset_id] = _coinbase_warmup_cached(
                        rows
                    )
                return (
                    registry_status,
                    products,
                    batch,
                    dynamic_open_ids,
                    market_ready,
                    warmup_cached,
                    attention_ids,
                )

            (
                registry_status,
                dynamic_products,
                dynamic_batch,
                dynamic_open_ids,
                prepared_dynamic_observations,
                dynamic_warmup_cached,
                dynamic_attention_ids,
            ) = await connection.run_sync(prepare)

        result["dynamic_product_registry"] = registry_status
        result["dynamic_roam"] = {
            "available": len(dynamic_products),
            "configured_scan_batch_size": configured_dynamic_strategy_scan_batch_size(),
            "configured_scan_batch_range": {"minimum": 1, "maximum": 20},
            "batch_size": len(dynamic_batch),
            "batch_asset_ids": [row.asset_id for row in dynamic_batch],
            "open_priority_asset_ids": list(dynamic_open_ids),
            "attention_priority_asset_ids": list(dynamic_attention_ids),
            "priority_is_allowlist": False,
        }

        # Resolve a real cross-venue warm-up product once per cycle. A catalog
        # failure degrades only dynamic history; it never stops the seed lane.
        coinbase_catalog: Mapping[tuple[str, str], str] = {}
        coinbase_catalog_error: str | None = None
        needs_coinbase_catalog = any(
            prepared_dynamic_observations.get(product.asset_id) is not None
            and not dynamic_warmup_cached.get(product.asset_id, False)
            for product in dynamic_batch
        )
        if needs_coinbase_catalog:
            try:
                coinbase_catalog = await fetch_coinbase_public_products(
                    timeout_s=20.0
                )
            except Exception as exc:
                coinbase_catalog_error = (
                    f"{type(exc).__name__}:{exc}"
                )

        history_by_asset: dict[str, DynamicStrategyHistory] = {}
        fetchable_products = tuple(
            product
            for product in dynamic_batch
            if prepared_dynamic_observations.get(product.asset_id) is not None
        )
        history_tasks = []
        for product in fetchable_products:
            needs_warmup = not dynamic_warmup_cached.get(
                product.asset_id,
                False,
            )
            if needs_warmup and coinbase_catalog_error is not None:
                history_by_asset[product.asset_id] = DynamicStrategyHistory(
                    asset_id=product.asset_id,
                    coinbase_product=None,
                    coinbase_hourly=(),
                    kraken_hourly=(),
                    kraken_daily=(),
                    error=(
                        "coinbase_catalog_error:"
                        + coinbase_catalog_error
                    ),
                )
                continue
            history_tasks.append(
                _fetch_dynamic_strategy_history(
                    product,
                    coinbase_products=coinbase_catalog,
                    end_at_utc=as_of_utc,
                    fetch_coinbase_warmup=needs_warmup,
                )
            )
        if history_tasks:
            histories = await asyncio.gather(*history_tasks)
            history_by_asset.update(
                {row.asset_id: row for row in histories}
            )

        # Second transaction: persist history and execute every eligible scan item.
        async with engine.begin() as connection:
            def cycle(sync_conn):
                inserted = 0
                for asset_id in ASSETS:
                    inserted += persist_prototype_market_bars(
                        sync_conn,
                        store,
                        tuple(
                            (
                                *fetched_hourly[asset_id],
                                *fetched_daily[asset_id],
                            )
                        ),
                        ingested_at_utc=as_of_utc,
                    )

                for history in history_by_asset.values():
                    if history.error is not None:
                        continue
                    inserted += persist_prototype_market_bars(
                        sync_conn,
                        store,
                        tuple(
                            (
                                *history.coinbase_hourly,
                                *history.kraken_hourly,
                                *history.kraken_daily,
                            )
                        ),
                        ingested_at_utc=as_of_utc,
                    )

                scan_asset_ids = tuple(
                    dict.fromkeys(
                        (*ASSETS, *(row.asset_id for row in dynamic_batch))
                    )
                )
                observations = {
                    asset_id: observation
                    for asset_id in scan_asset_ids
                    if (
                        observation := _latest_observation(
                            sync_conn,
                            store,
                            asset_id=asset_id,
                        )
                    ) is not None
                }

                decision_at_utc = datetime.now(UTC)
                (
                    observations,
                    clock_rejections,
                    exchange_clock_ahead_asset_ids,
                ) = _partition_observations_for_decision_time(
                    observations,
                    decision_at_utc=decision_at_utc,
                )
                result["decision_at_utc"] = decision_at_utc.isoformat()
                result["market_clock"] = {
                    "rejected_asset_ids": dict(sorted(clock_rejections.items())),
                    "exchange_clock_ahead_asset_ids": list(
                        exchange_clock_ahead_asset_ids
                    ),
                }

                open_table = store.tables["open_trades"]
                open_rows = tuple(
                    sync_conn.execute(
                        sa.select(open_table).where(
                            open_table.c.asset_id.in_(scan_asset_ids)
                        )
                    ).mappings()
                )
                assets_open_at_start = {
                    str(row["asset_id"]).strip().lower()
                    for row in open_rows
                }
                exit_results: dict[str, object] = {}

                # Manage every seed/dynamic OPEN trade included by the roaming planner.
                for trade in open_rows:
                    asset_id = str(trade["asset_id"]).strip().lower()
                    observation = observations.get(asset_id)
                    if observation is None:
                        exit_results[asset_id] = {
                            "stage": "OPEN",
                            "reason": clock_rejections.get(
                                asset_id,
                                "current_executable_observation_missing",
                            ),
                            "trade_id": str(trade["trade_id"]),
                        }
                        continue
                    hourly_rows = load_prototype_market_bars(
                        sync_conn,
                        store,
                        asset_id=asset_id,
                        interval_seconds=3600,
                        end_at_utc=decision_at_utc,
                    )
                    latest_bar = hourly_rows[-1] if hourly_rows else None
                    advanced = advance_prototype_crypto_exit(
                        sync_conn,
                        store,
                        trade_id=str(trade["trade_id"]),
                        current_observation=observation,
                        latest_completed_hourly_bar=latest_bar,
                        as_of_utc=decision_at_utc,
                    )
                    exit_results[asset_id] = asdict(advanced)

                seed_results: dict[str, object] = {}
                for asset_id in ASSETS:
                    observation = observations.get(asset_id)
                    if observation is None:
                        seed_results[asset_id] = {
                            "stage": "MARKET_NOT_READY",
                            "reason": clock_rejections.get(
                                asset_id,
                                "current_executable_observation_missing",
                            ),
                        }
                        continue
                    if asset_id in assets_open_at_start:
                        seed_results[asset_id] = {
                            "stage": "MANAGE_OPEN",
                            "reason": "trade_was_open_at_cycle_start",
                            "focus_selected": (
                                None
                                if focused_asset_ids is None
                                else asset_id in focused_asset_ids
                            ),
                        }
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
                            row
                            for row in hourly
                            if row.source_id == COINBASE_SOURCE_ID
                        ),
                        kraken_hourly=tuple(
                            row
                            for row in hourly
                            if row.source_id == KRAKEN_DAILY_SOURCE_ID
                        ),
                        asset_kraken_daily=tuple(
                            row
                            for row in asset_daily
                            if row.source_id == KRAKEN_DAILY_SOURCE_ID
                        ),
                        btc_kraken_daily=tuple(
                            row
                            for row in btc_daily
                            if row.source_id == KRAKEN_DAILY_SOURCE_ID
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
                        seed_results[asset_id] = {
                            "stage": "NO_REENTRY",
                            "reason": "completed_bar_setup_already_traded",
                            "trigger_close_utc": (
                                feature.trigger_close_utc.isoformat()
                            ),
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
                        "focus_selected": (
                            None
                            if focused_asset_ids is None
                            else asset_id in focused_asset_ids
                        ),
                        "watch_eligible": feature.watch_eligible,
                        "volatility_percentile": (
                            feature.volatility.percentile
                        ),
                    }
                    if advanced.stage == "NO_SETUP":
                        observation_new = (
                            persist_prototype_no_setup_observation(
                                sync_conn,
                                store,
                                paper_epoch_id=SANDBOX_SESSION_ID,
                                asset_id=asset_id,
                                trigger_close_utc=feature.trigger_close_utc,
                                evaluated_at_utc=decision_at_utc,
                                market_observation_id=(
                                    observation.observation_id
                                ),
                                reason=advanced.reason,
                                watch_eligible=feature.watch_eligible,
                                volatility_percentile=(
                                    feature.volatility.percentile
                                ),
                                setup_id=advanced.setup_id,
                                ticket_id=advanced.ticket_id,
                                order_intent_id=advanced.order_intent_id,
                            )
                        )
                        asset_result[
                            "forward_paper_observation_recorded"
                        ] = True
                        asset_result[
                            "forward_paper_observation_new"
                        ] = observation_new
                    seed_results[asset_id] = asset_result

                dynamic_results: dict[str, object] = {}
                product_by_id = {
                    product.asset_id: product
                    for product in dynamic_batch
                }
                btc_daily = load_prototype_market_bars(
                    sync_conn,
                    store,
                    asset_id="btc",
                    interval_seconds=86400,
                    end_at_utc=decision_at_utc,
                )

                for asset_id, product in product_by_id.items():
                    observation = observations.get(asset_id)
                    if observation is None:
                        dynamic_results[asset_id] = {
                            "stage": "MARKET_NOT_READY",
                            "reason": clock_rejections.get(
                                asset_id,
                                "current_executable_observation_missing",
                            ),
                        }
                        continue
                    if asset_id in assets_open_at_start:
                        dynamic_results[asset_id] = {
                            "stage": "MANAGE_OPEN",
                            "reason": "trade_was_open_at_cycle_start",
                        }
                        continue

                    history = history_by_asset.get(asset_id)
                    if history is None:
                        dynamic_results[asset_id] = {
                            "stage": "HISTORY_NOT_READY",
                            "reason": "history_not_fetched",
                        }
                        continue
                    if history.error is not None:
                        dynamic_results[asset_id] = {
                            "stage": "HISTORY_NOT_READY",
                            "reason": history.error,
                        }
                        continue

                    try:
                        spec = runtime_playbook_for_product(
                            product,
                            playbook_id="pb_crypto_swing_v1_2",
                        )
                    except Exception as exc:
                        dynamic_results[asset_id] = {
                            "stage": "EVALUATION_ERROR",
                            "reason": f"playbook:{type(exc).__name__}:{exc}",
                        }
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
                    try:
                        warmup = assemble_prototype_crypto_warmup(
                            asset_id=asset_id,
                            coinbase_hourly=tuple(
                                row
                                for row in hourly
                                if row.source_id == COINBASE_SOURCE_ID
                            ),
                            kraken_hourly=tuple(
                                row
                                for row in hourly
                                if row.source_id == KRAKEN_DAILY_SOURCE_ID
                            ),
                            asset_kraken_daily=tuple(
                                row
                                for row in asset_daily
                                if row.source_id == KRAKEN_DAILY_SOURCE_ID
                            ),
                            btc_kraken_daily=tuple(
                                row
                                for row in btc_daily
                                if row.source_id == KRAKEN_DAILY_SOURCE_ID
                            ),
                            as_of_utc=decision_at_utc,
                            playbook_spec=spec,
                        )
                    except Exception as exc:
                        dynamic_results[asset_id] = {
                            "stage": "HISTORY_NOT_READY",
                            "reason": f"warmup:{type(exc).__name__}:{exc}",
                        }
                        continue

                    feature = warmup.feature_snapshot
                    try:
                        plan = build_prototype_crypto_entry_plan(
                            feature=feature,
                            current_observation=observation,
                            as_of_utc=decision_at_utc,
                            playbook_spec=spec,
                        )
                    except Exception as exc:
                        dynamic_results[asset_id] = {
                            "stage": "EVALUATION_ERROR",
                            "reason": f"plan:{type(exc).__name__}:{exc}",
                        }
                        continue

                    if _setup_already_completed(
                        sync_conn,
                        store,
                        setup_id=plan.ids.setup_id,
                    ):
                        dynamic_results[asset_id] = {
                            "stage": "NO_REENTRY",
                            "reason": "completed_bar_setup_already_traded",
                            "trigger_close_utc": (
                                feature.trigger_close_utc.isoformat()
                            ),
                            "watch_eligible": feature.watch_eligible,
                        }
                        continue

                    try:
                        advanced = advance_prototype_crypto_entry(
                            sync_conn,
                            store,
                            plan=plan,
                            completed_bar=warmup.hourly_bars[-1],
                            current_observation=observation,
                            current_observations=observations,
                            as_of_utc=decision_at_utc,
                        )
                        dynamic_result = {
                            **asdict(advanced),
                            "watch_eligible": feature.watch_eligible,
                            "volatility_percentile": (
                                feature.volatility.percentile
                            ),
                            "coinbase_product": history.coinbase_product,
                        }
                        if advanced.stage == "NO_SETUP":
                            observation_new = (
                                persist_prototype_no_setup_observation(
                                    sync_conn,
                                    store,
                                    paper_epoch_id=SANDBOX_SESSION_ID,
                                    asset_id=asset_id,
                                    trigger_close_utc=(
                                        feature.trigger_close_utc
                                    ),
                                    evaluated_at_utc=decision_at_utc,
                                    market_observation_id=(
                                        observation.observation_id
                                    ),
                                    reason=advanced.reason,
                                    watch_eligible=feature.watch_eligible,
                                    volatility_percentile=(
                                        feature.volatility.percentile
                                    ),
                                    setup_id=advanced.setup_id,
                                    ticket_id=advanced.ticket_id,
                                    order_intent_id=(
                                        advanced.order_intent_id
                                    ),
                                )
                            )
                            dynamic_result[
                                "forward_paper_observation_recorded"
                            ] = True
                            dynamic_result[
                                "forward_paper_observation_new"
                            ] = observation_new
                        dynamic_results[asset_id] = dynamic_result
                    except Exception as exc:
                        dynamic_results[asset_id] = {
                            "stage": "PIPELINE_ERROR",
                            "reason": f"{type(exc).__name__}:{exc}",
                            "watch_eligible": feature.watch_eligible,
                        }

                focus_admitted = int(
                    (focus_snapshot or {}).get("focus_admitted_count")
                    or (focus_snapshot or {}).get("scout_received_count")
                    or (focus_snapshot or {}).get("focus_count")
                    or 0
                )
                evaluated = sum(
                    1
                    for row in dynamic_results.values()
                    if str(row.get("stage"))
                    not in {
                        "MARKET_NOT_READY",
                        "HISTORY_NOT_READY",
                        "EVALUATION_ERROR",
                    }
                )
                result["pipeline"] = {
                    "focus_admitted": focus_admitted,
                    "focus_received": focus_admitted,  # deprecated compatibility alias
                    "dynamic_kraken_available": len(dynamic_products),
                    "roaming_batch": len(dynamic_batch),
                    "market_ready": sum(
                        1
                        for asset_id in product_by_id
                        if asset_id in observations
                    ),
                    "history_ready": sum(
                        1
                        for row in history_by_asset.values()
                        if row.error is None
                    ),
                    "warmup_cache_hits": sum(
                        1
                        for product in dynamic_batch
                        if dynamic_warmup_cached.get(
                            product.asset_id,
                            False,
                        )
                    ),
                    "strategy_evaluated": evaluated,
                    "watch": _stage_count(dynamic_results, "WATCH"),
                    "fire_or_beyond": _stage_count(
                        dynamic_results,
                        "FIRE",
                        "SIZE",
                        "READY",
                        "RESERVED",
                        "SUBMITTED",
                        "OPEN",
                    ),
                    "market_not_ready": _stage_count(
                        dynamic_results,
                        "MARKET_NOT_READY",
                    ),
                    "history_not_ready": _stage_count(
                        dynamic_results,
                        "HISTORY_NOT_READY",
                    ),
                    "evaluation_error": _stage_count(
                        dynamic_results,
                        "EVALUATION_ERROR",
                        "PIPELINE_ERROR",
                    ),
                }

                result["inserted_market_bars"] = inserted
                result["current_observation_asset_ids"] = sorted(
                    observations
                )
                result["open_assets_at_cycle_start"] = sorted(
                    assets_open_at_start
                )
                result["exit_results"] = exit_results
                result["assets"] = seed_results
                result["dynamic_assets"] = dynamic_results
                result["paper_epoch_id"] = SANDBOX_SESSION_ID
                result["forward_paper_observation_count"] = (
                    count_prototype_no_setup_observations(
                        sync_conn,
                        store,
                        paper_epoch_id=SANDBOX_SESSION_ID,
                    )
                )

            await connection.run_sync(cycle)

    return result


def configured_strategy_enabled() -> bool:
    default = "true" if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() == "sandbox" else "false"
    raw = os.getenv("AETHER_VNEXT_SANDBOX_TRADING_ENABLED", default).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def configured_strategy_interval_seconds() -> float:
    raw = os.getenv("AETHER_VNEXT_SANDBOX_TRADING_INTERVAL_SECONDS", "15").strip()
    value = float(raw)
    if value < 5.0:
        raise ValueError("AETHER_VNEXT_SANDBOX_TRADING_INTERVAL_SECONDS must be >= 5")
    return value


def validate_configured_strategy_environment() -> None:
    if not configured_strategy_enabled():
        return
    if os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip().lower() != "sandbox":
        raise RuntimeError("sandbox strategy requires sandbox environment")
    if not PAPER_ONLY or not LIVE_BLOCKED:
        raise RuntimeError("prototype strategy safety invariant failed")
    VNextDatabaseConfig.from_environment()


def status_payload(
    status: PrototypeStrategySupervisorStatus,
) -> dict[str, object]:
    return asdict(status)
