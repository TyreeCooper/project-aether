"""Fail-closed planning boundary for canonical HELD_OUT historical research.

AETHER may not manufacture historical evidence. This module converts one reviewed
point-in-time ResearchDatasetSnapshot plus caller-supplied chronological folds into
an exact, deterministic no-cherry-pick replay work plan for the canonical executable
route universe.

The module does not load market history, calculate trade outcomes, write the database,
or create EvidenceWindow rows. Those actions remain downstream and must use real
reviewed data. Its job is to make the runner's required external inputs explicit and
to prevent an incomplete dataset, overlapping holdout folds, configuration drift, or
route cherry-picking from being mistaken for a startable research run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Mapping

from aether_vnext.forward_paper_preflight import (
    canonical_forward_paper_route_requests,
)
from aether_vnext.freeze import CONFIGURATION_HASH
from aether_vnext.indicator_authority import indicator_authority_blockers
from aether_vnext.playbooks import playbook
from aether_vnext.research import ResearchDatasetSnapshot


REQUIRED_INDICATORS = (
    "ema",
    "atr",
    "realized_vol",
    "volatility_percentile",
    "prior_closed_bar_range",
)
REPLAY_PLAN_VERSION = "aether-vnext-held-out-replay-plan-v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HASH64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HeldOutResearchRoutePlan:
    route_id: str
    playbook_id: str
    playbook_version: str
    mechanism_class: str


@dataclass(frozen=True, slots=True)
class HeldOutFoldPlan:
    fold_index: int
    train_start_utc: datetime
    train_end_utc: datetime
    test_start_utc: datetime
    test_end_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.fold_index, int) or isinstance(
            self.fold_index, bool
        ):
            raise ValueError("fold_index must be an integer")
        if self.fold_index < 0:
            raise ValueError("fold_index cannot be negative")
        for name in (
            "train_start_utc",
            "train_end_utc",
            "test_start_utc",
            "test_end_utc",
        ):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not (
            self.train_start_utc
            <= self.train_end_utc
            < self.test_start_utc
            <= self.test_end_utc
        ):
            raise ValueError(
                "held-out folds must be chronological and non-overlapping "
                "inside each fold"
            )


@dataclass(frozen=True, slots=True)
class HeldOutReplayInput:
    dataset_snapshot: ResearchDatasetSnapshot
    folds: tuple[HeldOutFoldPlan, ...]
    code_commit_sha: str
    configuration_hash: str


@dataclass(frozen=True, slots=True)
class HeldOutReplayWorkItem:
    work_item_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    mechanism_class: str
    dataset_snapshot_id: str
    dataset_content_hash: str
    fold_index: int
    test_start_utc: datetime
    test_end_utc: datetime
    code_commit_sha: str
    configuration_hash: str


@dataclass(frozen=True, slots=True)
class HeldOutResearchRunnerPreflight:
    route_count: int
    routes: tuple[HeldOutResearchRoutePlan, ...]
    required_indicators: tuple[str, ...]
    required_asset_ids: tuple[str, ...]
    dataset_snapshot_id: str | None
    fold_count: int
    work_item_count: int
    work_items: tuple[HeldOutReplayWorkItem, ...]
    blockers: tuple[str, ...]

    @property
    def startable(self) -> bool:
        return not self.blockers


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _hash64(value: object, name: str) -> str:
    text = _text(value, name)
    if not _HASH64.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 64-hex digest")
    return text


def _sha40(value: object, name: str) -> str:
    text = _text(value, name)
    if not _SHA40.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-hex commit SHA")
    return text


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    rows = tuple(_text(item, name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{name} cannot contain duplicates")
    return rows


def canonical_held_out_research_plan(
) -> tuple[HeldOutResearchRoutePlan, ...]:
    """Return the exact no-cherry-pick executable research universe."""
    rows = []
    for request in canonical_forward_paper_route_requests():
        spec = playbook(request.playbook_id)
        rows.append(
            HeldOutResearchRoutePlan(
                route_id=request.route_id,
                playbook_id=request.playbook_id,
                playbook_version=spec.version,
                mechanism_class=spec.mechanism_class,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (row.route_id, row.playbook_id),
        )
    )


def canonical_held_out_required_asset_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                row.route_id.split(":", 1)[0]
                for row in canonical_held_out_research_plan()
            }
        )
    )


def parse_held_out_replay_input(
    payload: Mapping[str, object],
) -> HeldOutReplayInput:
    """Parse reviewed replay inputs without creating research results."""
    if not isinstance(payload, Mapping):
        raise ValueError("replay plan must be a JSON object")

    version = _text(payload.get("plan_version"), "plan_version")
    if version != REPLAY_PLAN_VERSION:
        raise ValueError("unsupported held-out replay plan_version")

    configuration_hash = _hash64(
        payload.get("configuration_hash"),
        "configuration_hash",
    )
    code_commit_sha = _sha40(
        payload.get("code_commit_sha"),
        "code_commit_sha",
    )

    dataset_raw = payload.get("dataset")
    if not isinstance(dataset_raw, Mapping):
        raise ValueError("dataset must be a JSON object")
    asset_ids = _string_tuple(dataset_raw.get("asset_ids"), "asset_ids")
    if any(asset != asset.lower() for asset in asset_ids):
        raise ValueError("asset_ids must contain canonical lowercase IDs")

    snapshot = ResearchDatasetSnapshot(
        dataset_snapshot_id=_text(
            dataset_raw.get("dataset_snapshot_id"),
            "dataset_snapshot_id",
        ),
        created_at_utc=_utc(
            dataset_raw.get("created_at_utc"),
            "created_at_utc",
        ),
        as_of_utc=_utc(dataset_raw.get("as_of_utc"), "as_of_utc"),
        start_at_utc=_utc(
            dataset_raw.get("start_at_utc"),
            "start_at_utc",
        ),
        end_at_utc=_utc(
            dataset_raw.get("end_at_utc"),
            "end_at_utc",
        ),
        asset_ids=asset_ids,
        data_version=_text(
            dataset_raw.get("data_version"),
            "data_version",
        ),
        source_registry_version=_text(
            dataset_raw.get("source_registry_version"),
            "source_registry_version",
        ),
        product_registry_version=_text(
            dataset_raw.get("product_registry_version"),
            "product_registry_version",
        ),
        calendar_version=_text(
            dataset_raw.get("calendar_version"),
            "calendar_version",
        ),
        pit=dataset_raw.get("pit") is True,
        missing_data_policy=_text(
            dataset_raw.get("missing_data_policy"),
            "missing_data_policy",
        ),
        content_hash=_hash64(
            dataset_raw.get("content_hash"),
            "content_hash",
        ),
    )

    folds_raw = payload.get("folds")
    if not isinstance(folds_raw, list) or not folds_raw:
        raise ValueError("folds must be a non-empty list")
    folds: list[HeldOutFoldPlan] = []
    for row in folds_raw:
        if not isinstance(row, Mapping):
            raise ValueError("fold entries must be JSON objects")
        raw_index = row.get("fold_index")
        if isinstance(raw_index, bool):
            raise ValueError("fold_index must be an integer")
        try:
            fold_index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("fold_index must be an integer") from exc
        folds.append(
            HeldOutFoldPlan(
                fold_index=fold_index,
                train_start_utc=_utc(
                    row.get("train_start_utc"),
                    "train_start_utc",
                ),
                train_end_utc=_utc(
                    row.get("train_end_utc"),
                    "train_end_utc",
                ),
                test_start_utc=_utc(
                    row.get("test_start_utc"),
                    "test_start_utc",
                ),
                test_end_utc=_utc(
                    row.get("test_end_utc"),
                    "test_end_utc",
                ),
            )
        )

    return HeldOutReplayInput(
        dataset_snapshot=snapshot,
        folds=tuple(folds),
        code_commit_sha=code_commit_sha,
        configuration_hash=configuration_hash,
    )


def _input_blockers(
    input_: HeldOutReplayInput,
    *,
    required_asset_ids: tuple[str, ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    snapshot = input_.dataset_snapshot

    if input_.configuration_hash != CONFIGURATION_HASH:
        blockers.append("held_out_configuration_hash_mismatch")
    if not _SHA40.fullmatch(str(input_.code_commit_sha)):
        blockers.append("held_out_code_commit_sha_invalid")

    missing_assets = tuple(
        sorted(set(required_asset_ids) - set(snapshot.asset_ids))
    )
    if missing_assets:
        blockers.append(
            "held_out_dataset_missing_assets:" + ",".join(missing_assets)
        )

    if not input_.folds:
        blockers.append("held_out_fold_plan_required")
        return tuple(blockers)

    indices = tuple(row.fold_index for row in input_.folds)
    if len(indices) != len(set(indices)):
        blockers.append("held_out_fold_indices_duplicate")

    ordered = tuple(
        sorted(
            input_.folds,
            key=lambda row: (
                row.test_start_utc,
                row.test_end_utc,
                row.fold_index,
            ),
        )
    )
    for row in ordered:
        if (
            row.train_start_utc < snapshot.start_at_utc
            or row.test_end_utc > snapshot.end_at_utc
        ):
            blockers.append("held_out_fold_window_outside_dataset")
            break
    for prior, current in zip(ordered, ordered[1:]):
        if current.test_start_utc <= prior.test_end_utc:
            blockers.append("held_out_fold_test_windows_overlap")
            break

    return tuple(dict.fromkeys(blockers))


def _work_item_id(
    *,
    route: HeldOutResearchRoutePlan,
    snapshot: ResearchDatasetSnapshot,
    fold: HeldOutFoldPlan,
    code_commit_sha: str,
    configuration_hash: str,
) -> str:
    raw = json.dumps(
        {
            "route_id": route.route_id,
            "playbook_id": route.playbook_id,
            "playbook_version": route.playbook_version,
            "dataset_snapshot_id": snapshot.dataset_snapshot_id,
            "dataset_content_hash": snapshot.content_hash,
            "fold_index": fold.fold_index,
            "test_start_utc": fold.test_start_utc.isoformat(),
            "test_end_utc": fold.test_end_utc.isoformat(),
            "code_commit_sha": code_commit_sha,
            "configuration_hash": configuration_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _build_work_items(
    *,
    routes: tuple[HeldOutResearchRoutePlan, ...],
    input_: HeldOutReplayInput,
) -> tuple[HeldOutReplayWorkItem, ...]:
    snapshot = input_.dataset_snapshot
    folds = tuple(
        sorted(
            input_.folds,
            key=lambda row: (
                row.test_start_utc,
                row.test_end_utc,
                row.fold_index,
            ),
        )
    )
    rows: list[HeldOutReplayWorkItem] = []
    for route in routes:
        for fold in folds:
            rows.append(
                HeldOutReplayWorkItem(
                    work_item_id=_work_item_id(
                        route=route,
                        snapshot=snapshot,
                        fold=fold,
                        code_commit_sha=input_.code_commit_sha,
                        configuration_hash=input_.configuration_hash,
                    ),
                    route_id=route.route_id,
                    playbook_id=route.playbook_id,
                    playbook_version=route.playbook_version,
                    mechanism_class=route.mechanism_class,
                    dataset_snapshot_id=snapshot.dataset_snapshot_id,
                    dataset_content_hash=snapshot.content_hash,
                    fold_index=fold.fold_index,
                    test_start_utc=fold.test_start_utc,
                    test_end_utc=fold.test_end_utc,
                    code_commit_sha=input_.code_commit_sha,
                    configuration_hash=input_.configuration_hash,
                )
            )
    return tuple(rows)


def preflight_canonical_held_out_research_runner(
    input_: HeldOutReplayInput | None = None,
) -> HeldOutResearchRunnerPreflight:
    """Preflight indicator authority plus real replay-input integrity.

    A no-argument call intentionally fails closed after indicator math is bound:
    a real PIT dataset, chronological fold plan, and exact code commit are still
    required before historical replay can begin.
    """
    routes = canonical_held_out_research_plan()
    required_assets = canonical_held_out_required_asset_ids()
    blockers = list(
        indicator_authority_blockers(REQUIRED_INDICATORS)
    )

    if input_ is None:
        blockers.extend(
            (
                "held_out_dataset_snapshot_required",
                "held_out_fold_plan_required",
                "held_out_code_commit_sha_required",
            )
        )
        return HeldOutResearchRunnerPreflight(
            route_count=len(routes),
            routes=routes,
            required_indicators=REQUIRED_INDICATORS,
            required_asset_ids=required_assets,
            dataset_snapshot_id=None,
            fold_count=0,
            work_item_count=0,
            work_items=(),
            blockers=tuple(blockers),
        )

    blockers.extend(
        _input_blockers(
            input_,
            required_asset_ids=required_assets,
        )
    )
    work_items = (
        ()
        if blockers
        else _build_work_items(routes=routes, input_=input_)
    )
    return HeldOutResearchRunnerPreflight(
        route_count=len(routes),
        routes=routes,
        required_indicators=REQUIRED_INDICATORS,
        required_asset_ids=required_assets,
        dataset_snapshot_id=input_.dataset_snapshot.dataset_snapshot_id,
        fold_count=len(input_.folds),
        work_item_count=len(work_items),
        work_items=work_items,
        blockers=tuple(blockers),
    )
