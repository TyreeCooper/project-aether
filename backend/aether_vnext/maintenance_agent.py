"""AETHER Pipeline Maintenance diagnosis and bounded PAPER recovery."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.kraken_ingress_supervisor import (
    maintenance_quarantine_snapshot,
    maintenance_quarantine_symbols,
)
from aether_vnext.store import VNextStore

UTC = timezone.utc
MAINTENANCE_VERSION = "maintenance-agent-v2"
HEALTHY_PROFILE_VERSION = "HealthyPipelineProfile-v2"

CONTROL_DEFAULTS = {
    # Maintenance is intentionally inert on a fresh worker. Operator action is
    # required to arm background diagnosis/repair after the trading runtime is ready.
    "master_enabled": False,
    "diagnostics_enabled": True,
    "first_clog_enabled": True,
    "incident_history_enabled": True,
    "auto_repair_enabled": False,
    "level1_safe_repair_enabled": True,
    "level2_guarded_tuning_enabled": False,
    "code_repair_planning_enabled": False,
    "unsupported_symbol_quarantine_enabled": True,
}
CONTROL_LABELS = {
    "master_enabled": "Maintenance Agent",
    "diagnostics_enabled": "Detailed diagnostics",
    "first_clog_enabled": "First causal clog detection",
    "incident_history_enabled": "Incident history",
    "auto_repair_enabled": "Automatic repair",
    "level1_safe_repair_enabled": "Level 1 safe repairs",
    "level2_guarded_tuning_enabled": "Level 2 guarded tuning",
    "code_repair_planning_enabled": "Code repair planning",
    "unsupported_symbol_quarantine_enabled": "Unsupported-symbol quarantine",
}
_UNSUPPORTED_RE = re.compile(
    r"Currency pair not supported\s+([A-Z0-9._/-]+)",
    re.I,
)


class MaintenanceIdleTimeout(TimeoutError):
    """One maintenance step made no progress before the idle deadline."""

    def __init__(self, phase: str, timeout_seconds: float) -> None:
        self.phase = str(phase)
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"maintenance phase {self.phase} exceeded "
            f"{self.timeout_seconds:g}s idle deadline"
        )


@dataclass(frozen=True, slots=True)
class MaintenanceStatus:
    enabled: bool
    running: bool
    paper_only: bool
    live_blocked: bool
    cycle_count: int
    interval_seconds: float
    idle_timeout_seconds: float
    cycle_timeout_seconds: float
    last_cycle_started_at_utc: str | None
    last_cycle_finished_at_utc: str | None
    last_error: str | None
    last_result: dict[str, object] | None
    operation_kind: str | None
    operation_phase: str | None
    operation_started_at_utc: str | None
    operation_last_progress_at_utc: str | None
    last_timeout_phase: str | None
    healthy_baseline_established: bool


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _cycle_in_progress(status: Mapping[str, object]) -> bool:
    if status.get("running") is not True:
        return False
    started = _utc(status.get("last_cycle_started_at_utc"))
    finished = _utc(status.get("last_cycle_finished_at_utc"))
    return started is not None and (finished is None or started > finished)


def _newer_completed(
    upstream: Mapping[str, object],
    downstream: Mapping[str, object],
) -> bool:
    upstream_finished = _utc(upstream.get("last_cycle_finished_at_utc"))
    downstream_finished = _utc(downstream.get("last_cycle_finished_at_utc"))
    return (
        upstream_finished is not None
        and (
            downstream_finished is None
            or upstream_finished > downstream_finished
        )
    )


def _reasons(ingress: Mapping[str, object]) -> Counter[str]:
    rows = (ingress.get("last_result") or {}).get("asset_results") or []
    return Counter(
        str(row.get("reason") or "unknown")
        for row in rows
        if isinstance(row, Mapping) and row.get("executable") is not True
    )


def _unsupported(ingress: Mapping[str, object]) -> tuple[str, ...]:
    found: set[str] = set()
    for row in (ingress.get("last_result") or {}).get("batch_errors") or []:
        if not isinstance(row, Mapping):
            continue
        match = _UNSUPPORTED_RE.search(str(row.get("error") or ""))
        if match:
            found.add(match.group(1).upper())
    return tuple(sorted(found))


def diagnose_pipeline(
    *,
    ingress: Mapping[str, object],
    discovery: Mapping[str, object],
    strategy: Mapping[str, object],
    tape: Mapping[str, object] | None = None,
    floor: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Diagnose the first causal clog without treating supervisor skew as failure."""
    _ = floor
    disc = discovery.get("last_result") or {}
    strat = strategy.get("last_result") or {}
    pipe = strat.get("pipeline") or {}
    registry = strat.get("dynamic_product_registry") or {}
    roam = strat.get("dynamic_roam") or {}
    tape_payload = tape or {}
    tape_result = tape_payload.get("last_result") or {}
    tape_assets = (
        tape_result.get("assets")
        if isinstance(tape_result, Mapping)
        else ()
    ) or ()
    tape_states = Counter(
        str(row.get("state") or "NOT_OBSERVED")
        for row in tape_assets
        if isinstance(row, Mapping)
    )
    tape_full = _int(tape_states.get("FULL"))
    tape_required = tape is not None

    admitted = _int(disc.get("focus_admitted_count") or disc.get("focus_count"))
    providers = disc.get("providers") or {}
    kraken = providers.get("Kraken") if isinstance(providers, Mapping) else {}
    kraken_eligible = _int(
        kraken.get("eligible_count") if isinstance(kraken, Mapping) else 0
    )
    registry_received = _int(registry.get("received"))
    registry_persisted = _int(registry.get("persisted"))
    runtime_available = _int(
        roam.get("available") or pipe.get("dynamic_kraken_available")
    )
    roaming = _int(pipe.get("roaming_batch"))
    market = _int(pipe.get("market_ready"))
    history = _int(pipe.get("history_ready"))
    evaluated = _int(pipe.get("strategy_evaluated"))
    watch = _int(pipe.get("watch"))
    fire = _int(pipe.get("fire_or_beyond"))
    evaluation_errors = _int(pipe.get("evaluation_error"))

    reasons = _reasons(ingress)
    unsupported = _unsupported(ingress)
    ingress_rows = (ingress.get("last_result") or {}).get("asset_results") or []
    executable = sum(
        1
        for row in ingress_rows
        if isinstance(row, Mapping) and row.get("executable") is True
    )
    attempted = len(ingress_rows)

    status = "CLEAR"
    edge = "PIPELINE"
    owner = "Maintenance"
    reason = "healthy_pipeline"
    observed = "No first causal infrastructure clog detected."
    affected = 0
    not_root: list[str] = []
    downstream: list[str] = []
    confidence = "MEDIUM"

    faults: list[str] = []
    runtime_payloads = [
        ("ingress", ingress),
        ("discovery", discovery),
        ("strategy", strategy),
    ]
    if tape_required:
        runtime_payloads.insert(2, ("tape", tape_payload))
    for name, payload in runtime_payloads:
        if payload.get("enabled") is False:
            faults.append(name + "_disabled")
        elif payload.get("running") is not True:
            faults.append(name + "_not_running")
        if payload.get("last_error"):
            faults.append(name + ":" + str(payload.get("last_error")))

    first_cycles = [
        name
        for name, payload in runtime_payloads
        if payload.get("running") is True
        and _int(payload.get("cycle_count")) == 0
        and payload.get("last_result") is None
    ]
    tape_completed_without_full = (
        tape_required
        and _int(tape_payload.get("cycle_count")) > 0
        and tape_payload.get("last_result") is not None
        and tape_full == 0
    )
    discovery_ahead = (
        bool(disc)
        and _newer_completed(discovery, strategy)
    )
    ingress_ahead = (
        bool(ingress.get("last_result"))
        and _newer_completed(ingress, strategy)
    )

    if faults:
        status = "FAULT"
        edge = "RUNTIME"
        owner = "Runtime Supervisor"
        reason = faults[0]
        observed = "; ".join(faults[:4])
        affected = admitted or attempted
        confidence = "HIGH"
    elif first_cycles:
        status = "BUSY"
        edge = "RUNTIME→BASELINE"
        owner = "Runtime Supervisors"
        reason = "warming_first_cycle"
        observed = (
            "Healthy baseline is waiting on first completed cycle: "
            + ", ".join(first_cycles)
            + "."
        )
        confidence = "HIGH"
    elif discovery_ahead:
        status = "BUSY"
        edge = "DISCOVERY→STRATEGY_SYNC"
        owner = "Strategy Supervisor"
        reason = "awaiting_strategy_sync"
        observed = (
            "Discovery has a newer completed snapshot than Strategy. "
            "This is supervisor skew, not a pipeline blockage."
        )
        affected = admitted
        confidence = "HIGH"
    elif ingress_ahead and _cycle_in_progress(strategy):
        status = "BUSY"
        edge = "INGRESS→STRATEGY_SYNC"
        owner = "Strategy Supervisor"
        reason = "strategy_cycle_in_progress"
        observed = (
            "Fresh ingress arrived while the strategy cycle is still running. "
            "Wait for the current strategy pass before declaring a clog."
        )
        affected = roaming
        confidence = "HIGH"
    elif tape_completed_without_full:
        status = "DEGRADED"
        edge = "TAPE→MARKET_READY"
        owner = "AETHER Consensus Tape"
        reason = "tape_full_quorum_unavailable"
        observed = (
            "The Tape completed a cycle but no covered asset has FULL independent "
            "source quorum. New Tape-governed entries remain fail-closed."
        )
        affected = len(tape_assets)
        downstream = ["MARKET_READY", "HISTORY_READY", "STRATEGY_EVALUATED"]
        confidence = "HIGH"
    elif str(registry.get("status") or "") == "provider_policy_missing":
        status = "BLOCKED"
        edge = "FOCUS_ADMITTED→PRODUCT_BOUND"
        owner = "Runtime Product Binding"
        reason = "provider_policy_missing"
        observed = "Kraken provider policy is missing; dynamic products cannot bind."
        affected = kraken_eligible or admitted
        downstream = ["ROAMING_SCAN", "MARKET_READY", "STRATEGY_EVALUATED"]
        confidence = "HIGH"
    elif (
        registry_received > 0
        and registry_persisted == 0
        and runtime_available == 0
    ):
        status = "BLOCKED"
        edge = "FOCUS_ADMITTED→PRODUCT_BOUND"
        owner = "Runtime Product Binding"
        reason = "no_commissioned_runtime_products"
        observed = (
            f"{registry_received} Kraken products reached runtime binding; "
            "0 dynamic products were commissioned."
        )
        affected = registry_received
        downstream = ["ROAMING_SCAN", "MARKET_READY", "STRATEGY_EVALUATED"]
        confidence = "HIGH"
    elif runtime_available > 0 and roaming == 0:
        status = "BLOCKED"
        edge = "PRODUCT_BOUND→ROAMING_SCAN"
        owner = "Strategy Scheduler"
        reason = "roaming_scheduler_not_advancing"
        observed = (
            f"{runtime_available} commissioned dynamic products are available; "
            "0 were selected for this completed strategy cycle."
        )
        affected = runtime_available
        downstream = ["MARKET_READY", "HISTORY_READY", "STRATEGY_EVALUATED"]
        confidence = "HIGH"
    elif roaming > 0 and market == 0:
        status = "BLOCKED"
        edge = "ROAMING_SCAN→MARKET_READY"
        owner = "Market Ingress"
        reason = (
            reasons.most_common(1)[0][0]
            if reasons
            else "market_not_ready"
        )
        observed = (
            f"{roaming} scanning; 0 market-ready. "
            f"Ingress executable={executable}/{attempted}."
        )
        affected = max(roaming, attempted - executable)
        downstream = [
            "HISTORY_READY",
            "STRATEGY_EVALUATED",
            "WATCH",
            "FIRE",
            "SIZE",
            "READY",
            "OPEN",
        ]
        not_root = ["History", "Scout", "Sniper", "Risk", "Clerk", "Portfolio"]
        confidence = "HIGH"
    elif market > 0 and history == 0:
        status = "BLOCKED"
        edge = "MARKET_READY→HISTORY_READY"
        owner = "History / Warm-up"
        reason = "history_not_ready"
        observed = f"{market} market-ready; 0 history-ready."
        affected = market
        downstream = ["STRATEGY_EVALUATED", "WATCH", "OPEN"]
        not_root = ["Scout", "Risk", "Clerk", "Portfolio"]
        confidence = "HIGH"
    elif history > 0 and evaluated == 0:
        status = "BLOCKED"
        edge = "HISTORY_READY→STRATEGY_EVALUATED"
        owner = "Strategy Supervisor"
        reason = "evaluation_not_advancing"
        observed = f"{history} history-ready; 0 evaluated."
        affected = history
        downstream = ["WATCH", "FIRE", "OPEN"]
        confidence = "HIGH"
    elif evaluated > 0 and watch == 0 and evaluation_errors:
        status = "DEGRADED"
        edge = "STRATEGY_EVALUATED→WATCH"
        owner = "Scout / Strategy"
        reason = "evaluation_errors_present"
        observed = (
            f"{evaluated} evaluated; 0 WATCH; "
            f"{evaluation_errors} evaluation errors."
        )
        affected = evaluation_errors
        confidence = "HIGH"
    elif evaluated > 0 and watch == 0:
        status = "CLEAR"
        edge = "STRATEGY_EVALUATED→WATCH"
        owner = "Scout"
        reason = "no_natural_setup"
        observed = (
            f"{evaluated} assets evaluated normally; "
            "no natural setup qualified."
        )
        confidence = "HIGH"
    elif evaluated > 0:
        status = "CLEAR"
        edge = "PIPELINE"
        owner = "Maintenance"
        reason = "healthy_pipeline"
        observed = (
            f"{evaluated} assets evaluated; {watch} WATCH; "
            f"{fire} FIRE-or-beyond."
        )
        confidence = "HIGH"
    elif runtime_available == 0 and registry_received == 0:
        status = "BUSY"
        edge = "DISCOVERY→PRODUCT_BOUND"
        owner = "Discovery / Runtime Binding"
        reason = "awaiting_runtime_catalog"
        observed = (
            "Supervisors are running but no dynamic runtime catalog has been "
            "published yet."
        )
        affected = kraken_eligible
        confidence = "MEDIUM"

    recommendation = {
        "quote_stale": (
            "Inspect ingress cycle duration and provider batches before quotes age "
            "out; do not loosen strategy filters."
        ),
        "history_not_ready": (
            "Inspect warm-up coverage and per-asset history reasons before Scout."
        ),
        "provider_policy_missing": (
            "Restore the canonical Kraken runtime provider policy; do not bypass it."
        ),
        "no_commissioned_runtime_products": (
            "Inspect eligible Kraken product projection and runtime registry "
            "requirements."
        ),
        "roaming_scheduler_not_advancing": (
            "Inspect the bounded scheduler; Top-100 priority must not be an allowlist."
        ),
        "evaluation_not_advancing": "Inspect route-clock/evaluator errors.",
        "no_natural_setup": (
            "No repair required; the strategy evaluated normally and found no "
            "qualified setup."
        ),
        "awaiting_strategy_sync": (
            "Allow Strategy to consume the newer Discovery snapshot before "
            "classifying downstream zeroes."
        ),
        "warming_first_cycle": (
            "Wait for the first completed supervisor cycles; do not repair a "
            "startup state."
        ),
        "tape_full_quorum_unavailable": (
            "Inspect Tape source failures, freshness and divergence. Restore the "
            "three-source quorum; do not bypass Tape with broker-only market truth."
        ),
    }.get(
        reason,
        "Inspect the owning module and exact reason histogram before changing downstream gates.",
    )
    if unsupported:
        recommendation = (
            "Quarantine unsupported Kraken symbols from dynamic batches, then "
            "re-run ingress. " + recommendation
        )

    product_bound_input = registry_received or kraken_eligible
    product_bound_pass = runtime_available or registry_persisted
    stages = [
        {"stage": "FOCUS_ADMITTED", "input": admitted, "pass": admitted},
        {
            "stage": "PRODUCT_BOUND",
            "input": product_bound_input,
            "pass": product_bound_pass,
        },
        {
            "stage": "ROAMING_SCAN",
            "input": runtime_available,
            "pass": roaming,
        },
        {"stage": "MARKET_READY", "input": roaming, "pass": market},
        {"stage": "HISTORY_READY", "input": market, "pass": history},
        {"stage": "STRATEGY_EVALUATED", "input": history, "pass": evaluated},
        {"stage": "WATCH", "input": evaluated, "pass": watch},
        {"stage": "FIRE_OR_BEYOND", "input": watch, "pass": fire},
    ]

    maintenance_mode = {
        "CLEAR": "MAINTAINING",
        "BUSY": "CATCHING_UP",
        "DEGRADED": "RECOVERY",
        "BLOCKED": "RECOVERY",
        "FAULT": "FAULT",
    }.get(status, "RECOVERY")

    return {
        "version": MAINTENANCE_VERSION,
        "healthy_profile_version": HEALTHY_PROFILE_VERSION,
        "status": status,
        "maintenance_mode": maintenance_mode,
        "healthy_now": status == "CLEAR",
        "severity": (
            "HIGH"
            if status in {"BLOCKED", "FAULT"}
            else ("MEDIUM" if status == "DEGRADED" else "NONE")
        ),
        "first_causal_edge": edge,
        "owner": owner,
        "expected": (
            "Every active candidate has an explainable PASS/WAIT/KILL destination "
            "and async supervisor skew is classified as BUSY, not BLOCKED."
        ),
        "observed": observed,
        "affected_count": affected,
        "primary_reason": reason,
        "secondary_reasons": [
            {"reason": key, "count": value}
            for key, value in reasons.most_common(8)
            if key != reason
        ],
        "downstream_effects": downstream,
        "not_root_causes": not_root,
        "confidence": confidence,
        "tape_health": {
            "required": tape_required,
            "cycle_count": (
                None if not tape_required else _int(tape_payload.get("cycle_count"))
            ),
            "full": tape_full if tape_required else None,
            "degraded": (
                _int(tape_states.get("DEGRADED")) if tape_required else None
            ),
            "single_source": (
                _int(tape_states.get("SINGLE_SOURCE")) if tape_required else None
            ),
            "contested": (
                _int(tape_states.get("CONTESTED")) if tape_required else None
            ),
            "not_observed": (
                _int(tape_states.get("NOT_OBSERVED")) if tape_required else None
            ),
        },
        "unsupported_symbols": list(unsupported),
        "auto_fix_available": bool(unsupported)
        and status not in {"CLEAR", "BUSY"},
        "recommended_action": recommendation,
        "stages": stages,
        "healthy_system": {
            "unexplained_asset_loss": None,
            "orphan_reservations": None,
            "impossible_state_transitions": None,
            "live_orders": 0,
            "reconciliation_measurement": "UI/ledger telemetry required",
            "zero_trades_may_be_healthy": True,
            "zero_evaluations_with_runtime_candidates_is_unhealthy": True,
        },
        "paper_only": PAPER_ONLY,
        "live_blocked": LIVE_BLOCKED,
    }


async def load_controls() -> dict[str, bool]:
    store = VNextStore()
    async with open_vnext_engine() as engine:
        async with engine.connect() as conn:
            def read(sync_conn):
                table = store.tables["maintenance_controls"]
                saved = {
                    str(row["control_key"]): bool(row["enabled"])
                    for row in sync_conn.execute(sa.select(table)).mappings()
                }
                return {
                    key: saved.get(key, default)
                    for key, default in CONTROL_DEFAULTS.items()
                }

            return await conn.run_sync(read)


async def set_control(
    *,
    key: str,
    enabled: bool,
    actor: str,
) -> dict[str, bool]:
    if key not in CONTROL_DEFAULTS:
        raise KeyError(key)
    now = datetime.now(UTC)
    store = VNextStore()
    async with open_vnext_engine() as engine:
        async with engine.begin() as conn:
            def write(sync_conn):
                table = store.tables["maintenance_controls"]
                row = sync_conn.execute(
                    sa.select(table)
                    .where(table.c.control_key == key)
                    .with_for_update()
                ).mappings().first()
                if row is None:
                    sync_conn.execute(
                        table.insert().values(
                            control_key=key,
                            enabled=bool(enabled),
                            updated_at_utc=now,
                            updated_by=actor,
                            row_version=1,
                        )
                    )
                else:
                    sync_conn.execute(
                        table.update()
                        .where(table.c.control_key == key)
                        .values(
                            enabled=bool(enabled),
                            updated_at_utc=now,
                            updated_by=actor,
                            row_version=int(row["row_version"]) + 1,
                        )
                    )

            await conn.run_sync(write)
    return await load_controls()


async def record_incident(
    diagnosis: Mapping[str, object],
    repair: Mapping[str, object],
    *,
    controls: Mapping[str, bool] | None = None,
) -> None:
    if diagnosis.get("status") in {"CLEAR", "BUSY"}:
        return
    active_controls = (
        dict(controls)
        if controls is not None
        else await load_controls()
    )
    if not active_controls.get("incident_history_enabled", True):
        return

    now = datetime.now(UTC)
    fp_raw = (
        f"{diagnosis.get('first_causal_edge')}|"
        f"{diagnosis.get('primary_reason')}|"
        f"{diagnosis.get('owner')}"
    )
    fingerprint = hashlib.sha256(fp_raw.encode()).hexdigest()
    incident_id = "maint-" + fingerprint[:20]
    store = VNextStore()

    async with open_vnext_engine() as engine:
        async with engine.begin() as conn:
            def write(sync_conn):
                table = store.tables["maintenance_incidents"]
                row = sync_conn.execute(
                    sa.select(table)
                    .where(table.c.fingerprint == fingerprint)
                    .with_for_update()
                ).mappings().first()
                values = dict(
                    status=str(diagnosis.get("status")),
                    stage=str(diagnosis.get("first_causal_edge")),
                    owner=str(diagnosis.get("owner")),
                    reason=str(diagnosis.get("primary_reason")),
                    affected_count=_int(diagnosis.get("affected_count")),
                    diagnosis=dict(diagnosis),
                    repair=dict(repair),
                    last_seen_at_utc=now,
                    resolved=False,
                )
                if row is None:
                    sync_conn.execute(
                        table.insert().values(
                            incident_id=incident_id,
                            fingerprint=fingerprint,
                            first_seen_at_utc=now,
                            recurrence_count=1,
                            **values,
                        )
                    )
                else:
                    sync_conn.execute(
                        table.update()
                        .where(table.c.fingerprint == fingerprint)
                        .values(
                            recurrence_count=int(row["recurrence_count"]) + 1,
                            **values,
                        )
                    )

            await conn.run_sync(write)


async def close_cleared_incidents(diagnosis: Mapping[str, object]) -> int:
    """Persist incident closure when a later observed cycle clears the causal edge."""
    if diagnosis.get("status") not in {"CLEAR", "BUSY"}:
        return 0
    now = datetime.now(UTC)
    store = VNextStore()
    async with open_vnext_engine() as engine:
        async with engine.begin() as conn:
            def write(sync_conn):
                table = store.tables["maintenance_incidents"]
                rows = tuple(sync_conn.execute(sa.select(table).where(table.c.resolved.is_(False))).mappings())
                closed = 0
                for row in rows:
                    prior = dict(row.get("diagnosis") or {})
                    edge = str(prior.get("first_causal_edge") or row["stage"])
                    reason = str(prior.get("primary_reason") or row["reason"])
                    closure = {
                        "closed_at_utc": now.isoformat(),
                        "later_status": diagnosis.get("status"),
                        "later_edge": diagnosis.get("first_causal_edge"),
                        "later_reason": diagnosis.get("primary_reason"),
                        "result": "EDGE_CLEARED",
                    }
                    repair = {**dict(row.get("repair") or {}), "closure": closure}
                    sync_conn.execute(table.update().where(table.c.incident_id == row["incident_id"]).values(resolved=True, repair=repair, last_seen_at_utc=now))
                    closed += 1
                return closed
            return await conn.run_sync(write)


async def incident_history(limit: int = 20) -> list[dict[str, object]]:
    store = VNextStore()
    async with open_vnext_engine() as engine:
        async with engine.connect() as conn:
            def read(sync_conn):
                table = store.tables["maintenance_incidents"]
                rows = sync_conn.execute(
                    sa.select(table)
                    .order_by(table.c.last_seen_at_utc.desc())
                    .limit(max(1, min(limit, 100)))
                ).mappings()
                return [
                    {
                        **dict(row),
                        "first_seen_at_utc": row["first_seen_at_utc"].isoformat(),
                        "last_seen_at_utc": row["last_seen_at_utc"].isoformat(),
                    }
                    for row in rows
                ]

            return await conn.run_sync(read)


def safe_repair(
    diagnosis: Mapping[str, object],
    controls: Mapping[str, bool],
    *,
    force: bool = False,
) -> dict[str, object]:
    outcome: dict[str, object] = {
        "attempted": False,
        "level": None,
        "action": None,
        "result": "NO_ACTION",
        "rollback": "not_required",
        "verification": "not_required",
    }
    if diagnosis.get("status") in {"CLEAR", "BUSY"}:
        return outcome
    if not force and not controls.get("auto_repair_enabled", False):
        return outcome
    if (
        not controls.get("level1_safe_repair_enabled", True)
        or not controls.get("unsupported_symbol_quarantine_enabled", True)
    ):
        return outcome

    symbols = tuple(
        str(value)
        for value in diagnosis.get("unsupported_symbols") or []
    )
    if not symbols:
        return outcome

    before = list(maintenance_quarantine_snapshot())
    after = list(maintenance_quarantine_symbols(symbols))
    return {
        "attempted": True,
        "level": 1,
        "action": "quarantine_unsupported_kraken_symbols",
        "symbols": list(symbols),
        "before": before,
        "after": after,
        "result": "REPAIR_APPLIED",
        "rollback": "not_required",
        "verification": "pending_next_pipeline_cycle",
    }


StatusProvider = Callable[
    [],
    Mapping[str, object] | Awaitable[Mapping[str, object]],
]


class PipelineMaintenanceSupervisor:
    def __init__(
        self,
        *,
        ingress_provider: StatusProvider,
        discovery_provider: StatusProvider,
        strategy_provider: StatusProvider,
        tape_provider: StatusProvider | None = None,
        interval_seconds: float = 15.0,
        idle_timeout_seconds: float = 15.0,
        cycle_timeout_seconds: float = 30.0,
    ) -> None:
        self._ingress = ingress_provider
        self._discovery = discovery_provider
        self._strategy = strategy_provider
        self._tape = tape_provider
        self._interval = float(interval_seconds)
        self._idle_timeout = float(idle_timeout_seconds)
        self._cycle_timeout = float(cycle_timeout_seconds)
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._run_lock = asyncio.Lock()
        self._cycles = 0
        self._started: datetime | None = None
        self._finished: datetime | None = None
        self._error: str | None = None
        self._result: dict[str, object] | None = None
        self._operation_kind: str | None = None
        self._operation_phase: str | None = None
        self._operation_started: datetime | None = None
        self._operation_progress: datetime | None = None
        self._last_timeout_phase: str | None = None
        self._healthy_baseline = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _progress(self, phase: str) -> None:
        now = datetime.now(UTC)
        self._operation_phase = str(phase)
        self._operation_progress = now

    async def _step(self, awaitable, phase: str):
        self._progress(phase)
        try:
            return await asyncio.wait_for(
                awaitable,
                timeout=self._idle_timeout,
            )
        except TimeoutError as exc:
            self._last_timeout_phase = phase
            raise MaintenanceIdleTimeout(
                phase,
                self._idle_timeout,
            ) from exc

    async def _value(self, provider: StatusProvider):
        value = provider()
        return await value if inspect.isawaitable(value) else value

    async def run_once(
        self,
        *,
        force_repair: bool = False,
    ) -> dict[str, object]:
        async with self._run_lock:
            self._operation_kind = (
                "manual_repair" if force_repair else "maintenance_cycle"
            )
            self._operation_started = datetime.now(UTC)
            self._operation_progress = self._operation_started
            try:
                control_read_warning: str | None = None
                try:
                    controls = await self._step(
                        load_controls(),
                        "load_controls",
                    )
                except MaintenanceIdleTimeout:
                    if force_repair:
                        # Manual repair must honor persisted operator controls.
                        # If those controls cannot be read, fail closed.
                        raise
                    # Background diagnosis is read-only unless auto-repair is
                    # explicitly enabled. A cold/contended control-store read
                    # must not turn the trading pipeline red; continue with the
                    # conservative defaults and make the degraded control read
                    # explicit in telemetry. Auto repair remains OFF.
                    controls = dict(CONTROL_DEFAULTS)
                    controls["auto_repair_enabled"] = False
                    control_read_warning = (
                        "maintenance_control_store_timeout"
                    )
                    self._progress("controls_fallback")

                if not controls.get("master_enabled", True):
                    return {
                        "version": MAINTENANCE_VERSION,
                        "status": "DISABLED",
                        "maintenance_mode": "OFF",
                        "controls": controls,
                        "healthy_baseline_established": self._healthy_baseline,
                        "paper_only": True,
                        "live_blocked": True,
                    }
                if not controls.get("diagnostics_enabled", True):
                    return {
                        "version": MAINTENANCE_VERSION,
                        "status": "PAUSED",
                        "maintenance_mode": "PAUSED",
                        "controls": controls,
                        "healthy_baseline_established": self._healthy_baseline,
                        "paper_only": True,
                        "live_blocked": True,
                    }

                ingress = await self._step(
                    self._value(self._ingress),
                    "read_ingress",
                )
                discovery = await self._step(
                    self._value(self._discovery),
                    "read_discovery",
                )
                strategy = await self._step(
                    self._value(self._strategy),
                    "read_strategy",
                )
                tape = None
                if self._tape is not None:
                    tape = await self._step(
                        self._value(self._tape),
                        "read_tape",
                    )
                self._progress("diagnose")
                diagnosis = diagnose_pipeline(
                    ingress=ingress,
                    discovery=discovery,
                    strategy=strategy,
                    tape=tape,
                )

                if diagnosis.get("status") == "CLEAR":
                    self._healthy_baseline = True
                    if control_read_warning is None:
                        await self._step(
                            close_cleared_incidents(diagnosis),
                            "close_cleared_incidents",
                        )

                diagnosis["healthy_baseline_established"] = (
                    self._healthy_baseline
                )
                if not self._healthy_baseline:
                    diagnosis["maintenance_mode"] = (
                        "BASELINE_PENDING"
                        if diagnosis.get("status") in {"CLEAR", "BUSY"}
                        else "RECOVERY_BEFORE_BASELINE"
                    )

                self._progress("bounded_repair")
                repair = safe_repair(
                    diagnosis,
                    controls,
                    force=force_repair,
                )
                diagnosis["controls"] = controls
                diagnosis["repair"] = repair
                diagnosis["quarantined_symbols"] = list(
                    maintenance_quarantine_snapshot()
                )
                if control_read_warning is not None:
                    diagnosis["control_read_warning"] = (
                        control_read_warning
                    )
                    diagnosis["controls_source"] = (
                        "safe_defaults_after_timeout"
                    )
                    diagnosis["incident_persistence"] = (
                        "SKIPPED_CONTROL_STORE_TIMEOUT"
                    )
                else:
                    await self._step(
                        record_incident(
                            diagnosis,
                            repair,
                            controls=controls,
                        ),
                        "record_incident",
                    )
                self._progress("complete")
                return diagnosis
            finally:
                self._operation_kind = None
                self._operation_phase = None
                self._operation_started = None
                self._operation_progress = None

    def status(self) -> MaintenanceStatus:
        return MaintenanceStatus(
            enabled=True,
            running=self.running,
            paper_only=PAPER_ONLY,
            live_blocked=LIVE_BLOCKED,
            cycle_count=self._cycles,
            interval_seconds=self._interval,
            idle_timeout_seconds=self._idle_timeout,
            cycle_timeout_seconds=self._cycle_timeout,
            last_cycle_started_at_utc=(
                None if self._started is None else self._started.isoformat()
            ),
            last_cycle_finished_at_utc=(
                None if self._finished is None else self._finished.isoformat()
            ),
            last_error=self._error,
            last_result=self._result,
            operation_kind=self._operation_kind,
            operation_phase=self._operation_phase,
            operation_started_at_utc=(
                None
                if self._operation_started is None
                else self._operation_started.isoformat()
            ),
            operation_last_progress_at_utc=(
                None
                if self._operation_progress is None
                else self._operation_progress.isoformat()
            ),
            last_timeout_phase=self._last_timeout_phase,
            healthy_baseline_established=self._healthy_baseline,
        )

    async def start(self) -> None:
        if self.running:
            return
        if not PAPER_ONLY or not LIVE_BLOCKED:
            raise RuntimeError(
                "Maintenance requires PAPER_ONLY/LIVE_BLOCKED"
            )
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="aether-vnext-maintenance",
        )

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        stop = self._stop
        if stop is None:
            return
        while not stop.is_set():
            self._started = datetime.now(UTC)
            try:
                self._result = await asyncio.wait_for(
                    self.run_once(),
                    timeout=self._cycle_timeout,
                )
                self._error = None
                self._cycles += 1
            except asyncio.CancelledError:
                raise
            except MaintenanceIdleTimeout as exc:
                self._error = (
                    f"maintenance_idle_timeout:{exc.phase}:"
                    f"{exc.timeout_seconds:g}s"
                )
            except TimeoutError:
                self._last_timeout_phase = (
                    self._operation_phase or "cycle_total"
                )
                self._error = (
                    "maintenance_cycle_timeout:"
                    f"{self._cycle_timeout:g}s"
                )
            except Exception as exc:
                self._error = f"{type(exc).__name__}:{exc}"
            self._finished = datetime.now(UTC)
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self._interval,
                )
            except TimeoutError:
                continue


def configured_maintenance_interval_seconds() -> float:
    value = float(
        os.getenv("AETHER_VNEXT_MAINTENANCE_INTERVAL_SECONDS", "15")
    )
    if value < 5 or value > 300:
        raise ValueError("maintenance interval must be 5..300")
    return value


def configured_maintenance_idle_timeout_seconds() -> float:
    value = float(
        os.getenv("AETHER_VNEXT_MAINTENANCE_IDLE_TIMEOUT_SECONDS", "15")
    )
    if value < 3 or value > 60:
        raise ValueError("maintenance idle timeout must be 3..60")
    return value


def configured_maintenance_cycle_timeout_seconds() -> float:
    value = float(
        os.getenv("AETHER_VNEXT_MAINTENANCE_CYCLE_TIMEOUT_SECONDS", "30")
    )
    if value < 10 or value > 180:
        raise ValueError("maintenance cycle timeout must be 10..180")
    return value


def configured_maintenance_repair_timeout_seconds() -> float:
    value = float(
        os.getenv("AETHER_VNEXT_MAINTENANCE_REPAIR_TIMEOUT_SECONDS", "25")
    )
    if value < 5 or value > 120:
        raise ValueError("maintenance repair timeout must be 5..120")
    return value


def status_payload(
    status: MaintenanceStatus,
) -> dict[str, object]:
    return asdict(status)
