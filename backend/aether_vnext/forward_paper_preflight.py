"""Read-only forward-paper burn-in preflight.

This module inspects the vNext book and produces the exact campaign baseline that would
be used by start_forward_paper_campaign_from_book(). It performs no writes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.evidence import SampleDomain, independent_n
from aether_vnext.forward_paper import ForwardPaperRouteBaseline, parse_route_id
from aether_vnext.freeze import (
    CONFIGURATION_HASH,
    FORCED_ENTRIES_STRATEGY_TEST,
    LIVE_BLOCKED,
    PAPER_ONLY,
)
from aether_vnext.indicator_authority import indicator_authority_blockers
from aether_vnext.playbook_exits import exit_rule
from aether_vnext.playbooks import ordered_playbooks, playbook
from aether_vnext.registry_runtime import binding_blockers
from aether_vnext.runtime_book_health import runtime_book_blockers
from aether_vnext.store import VNextStore, canonical_payload_hash


@dataclass(frozen=True, slots=True)
class ForwardPaperRouteRequest:
    route_id: str
    playbook_id: str

    def __post_init__(self) -> None:
        if not str(self.route_id).strip():
            raise ValueError("route_id is required")
        if not str(self.playbook_id).strip():
            raise ValueError("playbook_id is required")


@dataclass(frozen=True, slots=True)
class ForwardPaperRouteExclusion:
    request: ForwardPaperRouteRequest
    reason: str


@dataclass(frozen=True, slots=True)
class ForwardPaperManifest:
    """Canonical WATCH coverage and the statically executable campaign subset."""

    coverage_requests: tuple[ForwardPaperRouteRequest, ...]
    executable_requests: tuple[ForwardPaperRouteRequest, ...]
    exclusions: tuple[ForwardPaperRouteExclusion, ...]

    @property
    def coverage_route_count(self) -> int:
        return len(self.coverage_requests)

    @property
    def executable_route_count(self) -> int:
        return len(self.executable_requests)

    @property
    def excluded_route_count(self) -> int:
        return len(self.exclusions)


def canonical_forward_paper_manifest() -> ForwardPaperManifest:
    """Build the no-cherry-pick campaign manifest from frozen source truth.

    WATCH coverage includes every Scout-definition-enabled route/playbook pair.
    Campaign execution additionally requires a source-complete ExitPlan contract.
    Market-data/broker environment readiness is a separate external preflight layer;
    this manifest does not invent those bindings.
    """
    coverage: list[ForwardPaperRouteRequest] = []
    executable: list[ForwardPaperRouteRequest] = []
    exclusions: list[ForwardPaperRouteExclusion] = []

    for spec in ordered_playbooks():
        if not spec.scout_definition_enabled:
            continue
        try:
            bound_exit = exit_rule(spec.playbook_id)
            exit_complete = bound_exit.source_complete
            exclusion_reason = (
                bound_exit.unresolved_reason
                or "exit_contract_incomplete"
            )
        except KeyError:
            exit_complete = False
            exclusion_reason = "exit_contract_missing"

        for asset_id, side, horizon in spec.route_tuples():
            request = ForwardPaperRouteRequest(
                route_id=f"{asset_id}:{horizon}:{side}",
                playbook_id=spec.playbook_id,
            )
            coverage.append(request)
            if exit_complete:
                executable.append(request)
            else:
                exclusions.append(
                    ForwardPaperRouteExclusion(
                        request=request,
                        reason=str(exclusion_reason),
                    )
                )

    key = lambda row: (row.route_id, row.playbook_id)
    exclusion_key = lambda row: (
        row.request.route_id,
        row.request.playbook_id,
    )
    return ForwardPaperManifest(
        coverage_requests=tuple(sorted(coverage, key=key)),
        executable_requests=tuple(sorted(executable, key=key)),
        exclusions=tuple(sorted(exclusions, key=exclusion_key)),
    )


def canonical_forward_paper_coverage_requests(
) -> tuple[ForwardPaperRouteRequest, ...]:
    """Return the complete WATCH-capable coverage universe."""
    return canonical_forward_paper_manifest().coverage_requests


def canonical_forward_paper_route_requests() -> tuple[ForwardPaperRouteRequest, ...]:
    """Return the complete statically executable no-cherry-pick campaign universe."""
    return canonical_forward_paper_manifest().executable_requests


@dataclass(frozen=True, slots=True)
class ForwardPaperRoutePreflight:
    request: ForwardPaperRouteRequest
    eligible: bool
    playbook_version: str | None
    held_out_window_ids: tuple[str, ...]
    held_out_window_count: int
    independent_held_out_n: int
    runtime_registry_binding_hash: str | None
    route_baseline_hash: str | None
    campaign_route_id: str | None
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForwardPaperPreflightResult:
    campaign_id: str
    configuration_hash: str
    policy_version: str | None
    requested_route_count: int
    startable: bool
    route_results: tuple[ForwardPaperRoutePreflight, ...]
    baseline_snapshot_hash: str | None
    blockers: tuple[str, ...]

    @property
    def missing_routes(self) -> tuple[str, ...]:
        return tuple(
            row.request.route_id
            for row in self.route_results
            if (
                "missing_current_held_out_baseline" in row.blockers
                or "held_out_baseline_lacks_research_provenance" in row.blockers
            )
        )


def _stored_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def forward_paper_campaign_route_id(
    *,
    campaign_id: str,
    route_id: str,
    playbook_id: str,
    playbook_version: str,
    configuration_hash: str,
    runtime_registry_binding_hash: str,
) -> str:
    """Return the canonical deterministic identity for one campaign route."""
    return _canonical_hash(
        {
            "campaign_id": campaign_id,
            "route_id": route_id,
            "playbook_id": playbook_id,
            "playbook_version": playbook_version,
            "configuration_hash": configuration_hash,
            "runtime_registry_binding_hash": runtime_registry_binding_hash,
        }
    )


def forward_paper_baseline_snapshot_hash(
    *,
    configuration_hash: str,
    policy_version: str,
    routes: tuple[ForwardPaperRouteBaseline, ...],
) -> str:
    """Hash one frozen campaign baseline using the canonical C9.1 payload."""
    ordered = tuple(
        sorted(
            routes,
            key=lambda row: (
                row.route_id,
                row.playbook_id,
                row.campaign_route_id,
            ),
        )
    )
    return _canonical_hash(
        {
            "configuration_hash": configuration_hash,
            "policy_version": policy_version,
            "routes": [
                {
                    "campaign_route_id": row.campaign_route_id,
                    "route_id": row.route_id,
                    "playbook_id": row.playbook_id,
                    "playbook_version": row.playbook_version,
                    "runtime_registry_binding_hash": (
                        row.runtime_registry_binding_hash
                    ),
                    "historical_validation_window_ids": list(
                        row.historical_validation_window_ids
                    ),
                    "historical_metrics_snapshot_hash": (
                        row.historical_metrics_snapshot_hash
                    ),
                }
                for row in ordered
            ],
        }
    )


def _route_baseline_hash(
    *,
    route_id: str,
    playbook_id: str,
    playbook_version: str,
    configuration_hash: str,
    runtime_registry_binding_hash: str,
    rows: tuple[dict[str, object], ...],
) -> str:
    return _canonical_hash(
        {
            "route_id": route_id,
            "playbook_id": playbook_id,
            "playbook_version": playbook_version,
            "configuration_hash": configuration_hash,
            "runtime_registry_binding_hash": runtime_registry_binding_hash,
            "held_out_windows": [
                {
                    "evidence_window_id": str(row["evidence_window_id"]),
                    "metrics_snapshot_hash": str(row["metrics_snapshot_hash"]),
                    "first_timestamp_utc": row["first_timestamp_utc"].isoformat(),
                    "last_timestamp_utc": row["last_timestamp_utc"].isoformat(),
                    "n": int(row["n"]),
                    "immutable_trade_ids": list(
                        row["immutable_trade_ids"] or []
                    ),
                    "research_provenance": {
                        "backtest_run_id": str(row["backtest_run_id"]),
                        "dataset_snapshot_id": str(row["dataset_snapshot_id"]),
                        "fold_result_ids": list(row["fold_result_ids"] or []),
                        "provenance_hash": str(row["provenance_hash"]),
                    },
                }
                for row in rows
            ],
        }
    )


def forward_paper_route_baseline_hash(
    *,
    route_id: str,
    playbook_id: str,
    playbook_version: str,
    configuration_hash: str,
    runtime_registry_binding_hash: str,
    rows: tuple[dict[str, object], ...],
) -> str:
    """Public canonical hash for one frozen forward-paper route baseline."""
    return _route_baseline_hash(
        route_id=route_id,
        playbook_id=playbook_id,
        playbook_version=playbook_version,
        configuration_hash=configuration_hash,
        runtime_registry_binding_hash=runtime_registry_binding_hash,
        rows=rows,
    )


def preflight_forward_paper_campaign_from_book(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    requested_routes: tuple[ForwardPaperRouteRequest, ...],
    as_of_utc: datetime | None = None,
    require_market_source_implementation: bool = False,
    require_market_print_implementation: bool = False,
    require_calendar_provider_implementation: bool = False,
    require_shortability_provider_implementation: bool = False,
) -> ForwardPaperPreflightResult:
    """Inspect whether the current vNext book can start a C9.1 campaign."""
    if not str(campaign_id).strip():
        raise ValueError("campaign_id is required")
    if not requested_routes:
        raise ValueError("requested_routes cannot be empty")

    blockers: list[str] = []
    if not PAPER_ONLY:
        blockers.append("paper_only_not_enabled")
    if not LIVE_BLOCKED:
        blockers.append("live_not_blocked")
    if FORCED_ENTRIES_STRATEGY_TEST:
        blockers.append("forced_strategy_entries_enabled")

    policies = store.tables["policy_snapshots"]
    policy = conn.execute(
        sa.select(policies).where(
            policies.c.configuration_hash == CONFIGURATION_HASH
        )
    ).mappings().first()
    policy_version = str(policy["policy_version"]) if policy is not None else None
    if policy is None:
        blockers.append("canonical_policy_snapshot_missing")

    seen: set[tuple[str, str]] = set()
    route_results: list[ForwardPaperRoutePreflight] = []
    baseline_payload: list[dict[str, object]] = []
    evidence = store.tables["evidence_windows"]
    provenance = store.tables["held_out_evidence_provenance"]
    runs = store.tables["backtest_runs"]
    datasets = store.tables["research_dataset_snapshots"]
    folds = store.tables["fold_results"]

    for request in sorted(
        requested_routes,
        key=lambda item: (item.route_id, item.playbook_id),
    ):
        route_blockers: list[str] = []
        key = (request.route_id, request.playbook_id)
        if key in seen:
            route_blockers.append("duplicate_route_playbook_request")
        seen.add(key)

        spec = None
        try:
            spec = playbook(request.playbook_id)
        except KeyError:
            route_blockers.append("unknown_playbook")

        if spec is not None and not spec.scout_definition_enabled:
            route_blockers.append("playbook_not_burnin_eligible")

        if spec is not None and spec.scout_definition_enabled:
            try:
                if not exit_rule(spec.playbook_id).source_complete:
                    route_blockers.append("exit_contract_incomplete")
            except KeyError:
                route_blockers.append("exit_contract_missing")

        asset_id: str | None = None
        side: str | None = None
        if spec is not None:
            try:
                asset_id, horizon, side = parse_route_id(request.route_id)
                if asset_id not in spec.allowed_assets:
                    route_blockers.append("asset_not_allowed_by_playbook")
                if horizon != spec.horizon:
                    route_blockers.append("horizon_mismatch")
                if side not in spec.allowed_sides:
                    route_blockers.append("side_not_allowed_by_playbook")
            except ValueError:
                route_blockers.append("invalid_route_id")

        contract_blockers = tuple(route_blockers)
        runtime_registry_binding_hash: str | None = None
        rows: tuple[dict[str, object], ...] = ()
        route_hash: str | None = None
        campaign_route_id: str | None = None
        independent_count = 0

        if (
            spec is not None
            and policy_version is not None
            and asset_id is not None
            and not contract_blockers
        ):
            runtime_binding = store.load_runtime_registry_binding(
                conn,
                asset_id=asset_id,
            )
            if runtime_binding is None:
                route_blockers.append("runtime_product_binding_missing")
            else:
                if (
                    runtime_binding["configuration_hash"]
                    != CONFIGURATION_HASH
                ):
                    route_blockers.append(
                        "runtime_product_binding_configuration_mismatch"
                    )
                else:
                    binding = runtime_binding["binding"]
                    runtime_blockers = binding_blockers(
                        binding,
                        as_of_utc=as_of_utc,
                        require_market_source_implementation=(
                            require_market_source_implementation
                        ),
                        require_market_print_implementation=(
                            require_market_print_implementation
                        ),
                        require_calendar_provider_implementation=(
                            require_calendar_provider_implementation
                        ),
                        require_shortability_provider_implementation=(
                            require_shortability_provider_implementation
                            and side == "short"
                        ),
                    )
                    route_blockers.extend(runtime_blockers)
                    if not runtime_blockers:
                        runtime_registry_binding_hash = str(
                            runtime_binding["binding_hash"]
                        )
            family_filter = sa.and_(
                evidence.c.route_id == request.route_id,
                evidence.c.playbook_id == request.playbook_id,
                evidence.c.playbook_version == spec.version,
                evidence.c.configuration_hash == CONFIGURATION_HASH,
                evidence.c.policy_version == policy_version,
                evidence.c.sample_domain == SampleDomain.HELD_OUT.value,
            )
            rows = tuple(
                dict(row)
                for row in conn.execute(
                    sa.select(
                        evidence,
                        provenance.c.backtest_run_id.label("backtest_run_id"),
                        provenance.c.dataset_snapshot_id.label(
                            "dataset_snapshot_id"
                        ),
                        provenance.c.fold_result_ids.label("fold_result_ids"),
                        provenance.c.provenance_hash.label("provenance_hash"),
                    )
                    .join(
                        provenance,
                        provenance.c.evidence_window_id
                        == evidence.c.evidence_window_id,
                    )
                    .where(family_filter)
                    .order_by(
                        evidence.c.first_timestamp_utc.asc(),
                        evidence.c.last_timestamp_utc.asc(),
                        evidence.c.evidence_window_id.asc(),
                    )
                ).mappings()
            )
            if not rows:
                unproven_count = int(
                    conn.execute(
                        sa.select(sa.func.count())
                        .select_from(evidence)
                        .where(family_filter)
                    ).scalar_one()
                )
                route_blockers.append(
                    "held_out_baseline_lacks_research_provenance"
                    if unproven_count > 0
                    else "missing_current_held_out_baseline"
                )
            else:
                provenance_shape_ok = all(
                    isinstance(row["fold_result_ids"], list)
                    and bool(row["fold_result_ids"])
                    and all(
                        str(value).strip()
                        for value in row["fold_result_ids"]
                    )
                    and len(row["fold_result_ids"])
                    == len(
                        {
                            str(value).strip()
                            for value in row["fold_result_ids"]
                        }
                    )
                    and bool(str(row["backtest_run_id"]).strip())
                    and bool(str(row["dataset_snapshot_id"]).strip())
                    and bool(str(row["provenance_hash"]).strip())
                    for row in rows
                )
                if not provenance_shape_ok:
                    route_blockers.append(
                        "held_out_baseline_provenance_invalid"
                    )

                run_provenance_ok = provenance_shape_ok
                if provenance_shape_ok:
                    for row in rows:
                        run = conn.execute(
                            sa.select(runs).where(
                                runs.c.backtest_run_id
                                == str(row["backtest_run_id"]).strip()
                            )
                        ).mappings().first()
                        if (
                            run is None
                            or str(run["run_type"]).strip().lower()
                            != "held_out"
                            or run["finished_at_utc"] is None
                            or str(run["playbook_id"])
                            != request.playbook_id
                            or str(run["playbook_version"])
                            != spec.version
                            or str(run["configuration_hash"])
                            != CONFIGURATION_HASH
                            or str(run["dataset_snapshot_id"])
                            != str(row["dataset_snapshot_id"]).strip()
                        ):
                            run_provenance_ok = False
                            break
                if not run_provenance_ok:
                    route_blockers.append(
                        "held_out_provenance_run_invalid"
                    )

                dataset_provenance_ok = provenance_shape_ok
                if provenance_shape_ok:
                    for row in rows:
                        dataset = conn.execute(
                            sa.select(datasets).where(
                                datasets.c.dataset_snapshot_id
                                == str(row["dataset_snapshot_id"]).strip()
                            )
                        ).mappings().first()
                        if dataset is None:
                            dataset_provenance_ok = False
                            break
                        raw_asset_ids = dataset["asset_ids"]
                        dataset_asset_ids = (
                            tuple(
                                str(value).strip().lower()
                                for value in raw_asset_ids
                            )
                            if isinstance(raw_asset_ids, list)
                            else ()
                        )
                        if (
                            not bool(dataset["pit"])
                            or not isinstance(raw_asset_ids, list)
                            or not dataset_asset_ids
                            or any(not value for value in dataset_asset_ids)
                            or len(dataset_asset_ids)
                            != len(set(dataset_asset_ids))
                            or asset_id not in set(dataset_asset_ids)
                        ):
                            dataset_provenance_ok = False
                            break
                if not dataset_provenance_ok:
                    route_blockers.append(
                        "held_out_provenance_dataset_invalid"
                    )

                fold_provenance_ok = provenance_shape_ok
                if provenance_shape_ok:
                    for row in rows:
                        fold_ids = tuple(
                            str(value).strip()
                            for value in row["fold_result_ids"]
                        )
                        selected = tuple(
                            dict(fold)
                            for fold in conn.execute(
                                sa.select(folds).where(
                                    folds.c.fold_result_id.in_(fold_ids)
                                )
                            ).mappings()
                        )
                        if (
                            len(selected) != len(fold_ids)
                            or any(
                                str(fold["backtest_run_id"])
                                != str(row["backtest_run_id"]).strip()
                                for fold in selected
                            )
                        ):
                            fold_provenance_ok = False
                            break
                        ordered = tuple(
                            sorted(
                                selected,
                                key=lambda fold: (
                                    _stored_utc(fold["test_start_utc"]),
                                    _stored_utc(fold["test_end_utc"]),
                                    str(fold["fold_result_id"]),
                                ),
                            )
                        )
                        overlaps = any(
                            _stored_utc(current["test_start_utc"])
                            <= _stored_utc(prior["test_end_utc"])
                            for prior, current in zip(
                                ordered,
                                ordered[1:],
                            )
                        )
                        first_test_at = min(
                            _stored_utc(fold["test_start_utc"])
                            for fold in ordered
                        )
                        last_test_at = max(
                            _stored_utc(fold["test_end_utc"])
                            for fold in ordered
                        )
                        if (
                            overlaps
                            or _stored_utc(row["first_timestamp_utc"])
                            < first_test_at
                            or _stored_utc(row["last_timestamp_utc"])
                            > last_test_at
                        ):
                            fold_provenance_ok = False
                            break
                if not fold_provenance_ok:
                    route_blockers.append(
                        "held_out_provenance_fold_invalid"
                    )

                provenance_hash_ok = provenance_shape_ok
                if provenance_shape_ok:
                    for row in rows:
                        raw_trade_ids = row["immutable_trade_ids"]
                        if not isinstance(raw_trade_ids, list):
                            provenance_hash_ok = False
                            break
                        expected_provenance_hash = canonical_payload_hash(
                            {
                                "backtest_run_id": str(
                                    row["backtest_run_id"]
                                ).strip(),
                                "dataset_snapshot_id": str(
                                    row["dataset_snapshot_id"]
                                ).strip(),
                                "fold_result_ids": sorted(
                                    str(value).strip()
                                    for value in row["fold_result_ids"]
                                ),
                                "route_id": str(row["route_id"]),
                                "playbook_id": str(row["playbook_id"]),
                                "playbook_version": str(
                                    row["playbook_version"]
                                ),
                                "configuration_hash": str(
                                    row["configuration_hash"]
                                ),
                                "immutable_trade_ids": sorted(
                                    str(value).strip()
                                    for value in raw_trade_ids
                                ),
                                "metrics_snapshot_hash": str(
                                    row["metrics_snapshot_hash"]
                                ),
                            }
                        )
                        if expected_provenance_hash != str(
                            row["provenance_hash"]
                        ):
                            provenance_hash_ok = False
                            break
                if not provenance_hash_ok:
                    route_blockers.append(
                        "held_out_provenance_hash_invalid"
                    )
                try:
                    windows = tuple(
                        store.load_evidence_window(
                            conn,
                            evidence_window_id=str(row["evidence_window_id"]),
                        )
                        for row in rows
                    )
                except (TypeError, ValueError):
                    windows = ()
                    route_blockers.append("held_out_window_reload_failed")
                if any(window is None for window in windows):
                    route_blockers.append("held_out_window_reload_failed")
                elif windows:
                    concrete = tuple(
                        window for window in windows if window is not None
                    )
                    independent_count = independent_n(concrete)
                    if (
                        runtime_registry_binding_hash is not None
                        and provenance_shape_ok
                        and run_provenance_ok
                        and dataset_provenance_ok
                        and fold_provenance_ok
                        and provenance_hash_ok
                    ):
                        route_hash = _route_baseline_hash(
                            route_id=request.route_id,
                            playbook_id=request.playbook_id,
                            playbook_version=spec.version,
                            configuration_hash=CONFIGURATION_HASH,
                            runtime_registry_binding_hash=(
                                runtime_registry_binding_hash
                            ),
                            rows=rows,
                        )
                    if route_hash is not None:
                        campaign_route_id = forward_paper_campaign_route_id(
                            campaign_id=campaign_id,
                            route_id=request.route_id,
                            playbook_id=request.playbook_id,
                            playbook_version=spec.version,
                            configuration_hash=CONFIGURATION_HASH,
                            runtime_registry_binding_hash=(
                                runtime_registry_binding_hash
                            ),
                        )
                        if not route_blockers:
                            baseline_payload.append(
                                {
                                    "campaign_route_id": campaign_route_id,
                                    "route_id": request.route_id,
                                    "playbook_id": request.playbook_id,
                                    "playbook_version": spec.version,
                                    "runtime_registry_binding_hash": (
                                        runtime_registry_binding_hash
                                    ),
                                    "historical_validation_window_ids": [
                                        str(row["evidence_window_id"])
                                        for row in rows
                                    ],
                                    "historical_metrics_snapshot_hash": route_hash,
                                }
                            )

        route_results.append(
            ForwardPaperRoutePreflight(
                request=request,
                eligible=not route_blockers,
                playbook_version=(spec.version if spec is not None else None),
                held_out_window_ids=tuple(
                    str(row["evidence_window_id"]) for row in rows
                ),
                held_out_window_count=len(rows),
                independent_held_out_n=independent_count,
                runtime_registry_binding_hash=runtime_registry_binding_hash,
                route_baseline_hash=route_hash,
                campaign_route_id=campaign_route_id,
                blockers=tuple(dict.fromkeys(route_blockers)),
            )
        )

    if any(row.blockers for row in route_results):
        blockers.append("one_or_more_routes_not_startable")

    baseline_snapshot_hash: str | None = None
    if not blockers and policy_version is not None:
        baseline_routes = tuple(
            ForwardPaperRouteBaseline(
                campaign_route_id=str(row["campaign_route_id"]),
                campaign_id=campaign_id,
                route_id=str(row["route_id"]),
                playbook_id=str(row["playbook_id"]),
                playbook_version=str(row["playbook_version"]),
                configuration_hash=CONFIGURATION_HASH,
                runtime_registry_binding_hash=str(
                    row["runtime_registry_binding_hash"]
                ),
                historical_validation_window_ids=tuple(
                    str(value)
                    for value in row["historical_validation_window_ids"]
                ),
                historical_metrics_snapshot_hash=str(
                    row["historical_metrics_snapshot_hash"]
                ),
            )
            for row in baseline_payload
        )
        baseline_snapshot_hash = forward_paper_baseline_snapshot_hash(
            configuration_hash=CONFIGURATION_HASH,
            policy_version=policy_version,
            routes=baseline_routes,
        )

    return ForwardPaperPreflightResult(
        campaign_id=campaign_id,
        configuration_hash=CONFIGURATION_HASH,
        policy_version=policy_version,
        requested_route_count=len(requested_routes),
        startable=not blockers,
        route_results=tuple(route_results),
        baseline_snapshot_hash=baseline_snapshot_hash,
        blockers=tuple(dict.fromkeys(blockers)),
    )



def preflight_canonical_forward_paper_campaign_from_book(
    conn: Connection,
    store: VNextStore,
    *,
    campaign_id: str,
    as_of_utc: datetime | None = None,
) -> ForwardPaperPreflightResult:
    """Preflight the full canonical executable campaign universe only."""
    effective_as_of = as_of_utc or datetime.now(timezone.utc)
    result = preflight_forward_paper_campaign_from_book(
        conn,
        store,
        campaign_id=campaign_id,
        requested_routes=canonical_forward_paper_route_requests(),
        as_of_utc=effective_as_of,
        require_market_source_implementation=True,
        require_market_print_implementation=True,
        require_calendar_provider_implementation=True,
        require_shortability_provider_implementation=True,
    )
    indicator_blockers = indicator_authority_blockers(
        (
            "ema",
            "atr",
            "realized_vol",
            "prior_closed_bar_range",
        )
    )
    book_blockers = runtime_book_blockers(
        conn,
        store=store,
        as_of_utc=effective_as_of,
    )
    additional_blockers = (*indicator_blockers, *book_blockers)
    if not additional_blockers:
        return result

    return replace(
        result,
        startable=False,
        baseline_snapshot_hash=None,
        blockers=tuple(
            dict.fromkeys((*result.blockers, *additional_blockers))
        ),
    )

def route_baselines_from_preflight(
    result: ForwardPaperPreflightResult,
) -> tuple[ForwardPaperRouteBaseline, ...]:
    if not result.startable:
        raise ValueError("preflight is not startable")
    out: list[ForwardPaperRouteBaseline] = []
    for row in result.route_results:
        if (
            row.playbook_version is None
            or row.runtime_registry_binding_hash is None
            or row.route_baseline_hash is None
            or row.campaign_route_id is None
        ):
            raise RuntimeError("startable preflight contains incomplete route")
        out.append(
            ForwardPaperRouteBaseline(
                campaign_route_id=row.campaign_route_id,
                campaign_id=result.campaign_id,
                route_id=row.request.route_id,
                playbook_id=row.request.playbook_id,
                playbook_version=row.playbook_version,
                configuration_hash=result.configuration_hash,
                runtime_registry_binding_hash=(
                    row.runtime_registry_binding_hash
                ),
                historical_validation_window_ids=row.held_out_window_ids,
                historical_metrics_snapshot_hash=row.route_baseline_hash,
            )
        )
    return tuple(out)
