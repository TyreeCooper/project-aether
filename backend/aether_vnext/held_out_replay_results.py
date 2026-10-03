"""No-cherry-pick result coverage for canonical AETHER HELD_OUT replay.

The replay planner defines the exact route x fold work universe. This module validates
that externally produced real replay outputs account for every work item exactly once.

It does not create trades, metrics, pass/fail verdicts, or evidence. It only binds
terminal output identity back to the deterministic work plan and prevents missing,
extra, mismatched, or multiply-counted work from masquerading as complete research.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json

from aether_vnext.held_out_research_runner import (
    HeldOutResearchRunnerPreflight,
    HeldOutReplayWorkItem,
)


class ReplayResultStatus(StrEnum):
    COMPLETE = "COMPLETE"
    FAILED_EVIDENCE = "FAILED_EVIDENCE"


@dataclass(frozen=True, slots=True)
class HeldOutReplayResultRecord:
    work_item_id: str
    route_id: str
    playbook_id: str
    playbook_version: str
    fold_index: int
    status: ReplayResultStatus
    immutable_trade_ids: tuple[str, ...]
    result_hash: str

    def __post_init__(self) -> None:
        for name in (
            "work_item_id",
            "route_id",
            "playbook_id",
            "playbook_version",
            "result_hash",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be canonical text")
        if not isinstance(self.fold_index, int) or isinstance(self.fold_index, bool):
            raise ValueError("fold_index must be an integer")
        if self.fold_index < 0:
            raise ValueError("fold_index cannot be negative")
        if not isinstance(self.immutable_trade_ids, tuple):
            raise ValueError("immutable_trade_ids must be an immutable tuple")
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            for value in self.immutable_trade_ids
        ):
            raise ValueError("immutable_trade_ids must contain canonical IDs")
        if len(self.immutable_trade_ids) != len(set(self.immutable_trade_ids)):
            raise ValueError("duplicate trade ID inside replay result")


@dataclass(frozen=True, slots=True)
class ReplayCoverageReport:
    expected_work_item_count: int
    supplied_result_count: int
    missing_work_item_ids: tuple[str, ...]
    unexpected_work_item_ids: tuple[str, ...]
    duplicate_trade_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return (
            self.expected_work_item_count == self.supplied_result_count
            and not self.missing_work_item_ids
            and not self.unexpected_work_item_ids
            and not self.duplicate_trade_ids
        )


def replay_result_hash(
    work_item: HeldOutReplayWorkItem,
    *,
    status: ReplayResultStatus,
    immutable_trade_ids: tuple[str, ...],
) -> str:
    raw = json.dumps(
        {
            "work_item_id": work_item.work_item_id,
            "route_id": work_item.route_id,
            "playbook_id": work_item.playbook_id,
            "playbook_version": work_item.playbook_version,
            "fold_index": work_item.fold_index,
            "status": status.value,
            "immutable_trade_ids": list(immutable_trade_ids),
            "dataset_snapshot_id": work_item.dataset_snapshot_id,
            "dataset_content_hash": work_item.dataset_content_hash,
            "code_commit_sha": work_item.code_commit_sha,
            "configuration_hash": work_item.configuration_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bind_replay_result(
    work_item: HeldOutReplayWorkItem,
    *,
    status: ReplayResultStatus,
    immutable_trade_ids: tuple[str, ...],
) -> HeldOutReplayResultRecord:
    ids = tuple(immutable_trade_ids)
    return HeldOutReplayResultRecord(
        work_item_id=work_item.work_item_id,
        route_id=work_item.route_id,
        playbook_id=work_item.playbook_id,
        playbook_version=work_item.playbook_version,
        fold_index=work_item.fold_index,
        status=status,
        immutable_trade_ids=ids,
        result_hash=replay_result_hash(
            work_item,
            status=status,
            immutable_trade_ids=ids,
        ),
    )


def validate_replay_result_coverage(
    preflight: HeldOutResearchRunnerPreflight,
    results: tuple[HeldOutReplayResultRecord, ...],
) -> ReplayCoverageReport:
    if not preflight.startable:
        raise ValueError(
            "held-out replay result coverage requires startable replay preflight"
        )

    expected = {row.work_item_id: row for row in preflight.work_items}
    if len(expected) != len(preflight.work_items):
        raise ValueError("replay preflight contains duplicate work_item_id")

    supplied: dict[str, HeldOutReplayResultRecord] = {}
    for row in results:
        if row.work_item_id in supplied:
            raise ValueError(
                f"duplicate replay result for work_item_id: {row.work_item_id}"
            )
        supplied[row.work_item_id] = row

        work = expected.get(row.work_item_id)
        if work is None:
            continue
        if (
            row.route_id != work.route_id
            or row.playbook_id != work.playbook_id
            or row.playbook_version != work.playbook_version
            or row.fold_index != work.fold_index
        ):
            raise ValueError(
                f"replay result identity mismatch for {row.work_item_id}"
            )
        expected_hash = replay_result_hash(
            work,
            status=row.status,
            immutable_trade_ids=row.immutable_trade_ids,
        )
        if row.result_hash != expected_hash:
            raise ValueError(
                f"replay result hash mismatch for {row.work_item_id}"
            )

    expected_ids = set(expected)
    supplied_ids = set(supplied)
    missing = tuple(sorted(expected_ids - supplied_ids))
    unexpected = tuple(sorted(supplied_ids - expected_ids))

    trade_owner: dict[str, str] = {}
    duplicate_trades: set[str] = set()
    for row in results:
        for trade_id in row.immutable_trade_ids:
            owner = trade_owner.get(trade_id)
            if owner is not None and owner != row.work_item_id:
                duplicate_trades.add(trade_id)
            else:
                trade_owner[trade_id] = row.work_item_id

    return ReplayCoverageReport(
        expected_work_item_count=len(expected),
        supplied_result_count=len(results),
        missing_work_item_ids=missing,
        unexpected_work_item_ids=unexpected,
        duplicate_trade_ids=tuple(sorted(duplicate_trades)),
    )


def require_complete_replay_result_coverage(
    preflight: HeldOutResearchRunnerPreflight,
    results: tuple[HeldOutReplayResultRecord, ...],
) -> ReplayCoverageReport:
    report = validate_replay_result_coverage(preflight, results)
    if not report.complete:
        problems = []
        if report.missing_work_item_ids:
            problems.append("missing_work_items")
        if report.unexpected_work_item_ids:
            problems.append("unexpected_work_items")
        if report.duplicate_trade_ids:
            problems.append("duplicate_trade_ids")
        raise ValueError(
            "held-out replay result coverage incomplete: " + ",".join(problems)
        )
    return report
