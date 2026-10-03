"""Assemble immutable research-bar manifests from reviewed normalized rows.

This module is provider-neutral. It does not download data, fill missing intervals,
repair prices, infer provider timestamp semantics, or persist anything.

Callers must supply already-reviewed normalized rows with explicit bucket open/close
and availability timestamps. The assembler computes deterministic ResearchBar IDs,
the content-addressed dataset hash, and runs the existing warehouse validator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from aether_vnext.research import ResearchDatasetSnapshot
from aether_vnext.research_warehouse import (
    RESEARCH_BAR_MANIFEST_VERSION,
    ResearchBarManifest,
    ResearchBarRecord,
    _canonical_bar_payload,
    research_bar_id,
    research_dataset_content_hash,
    validate_research_bar_manifest,
)


_ZERO_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class ResearchDatasetSpec:
    dataset_snapshot_id: str
    created_at_utc: datetime
    as_of_utc: datetime
    start_at_utc: datetime
    end_at_utc: datetime
    asset_ids: tuple[str, ...]
    data_version: str
    source_registry_version: str
    product_registry_version: str
    calendar_version: str
    missing_data_policy: str


@dataclass(frozen=True, slots=True)
class ResearchBarManifestAssembly:
    manifest: ResearchBarManifest
    validation_report: dict[str, object]


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _number(value: object, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _provisional_snapshot(spec: ResearchDatasetSpec) -> ResearchDatasetSnapshot:
    return ResearchDatasetSnapshot(
        dataset_snapshot_id=_text(
            spec.dataset_snapshot_id,
            "dataset_snapshot_id",
        ),
        created_at_utc=_utc(spec.created_at_utc, "created_at_utc"),
        as_of_utc=_utc(spec.as_of_utc, "as_of_utc"),
        start_at_utc=_utc(spec.start_at_utc, "start_at_utc"),
        end_at_utc=_utc(spec.end_at_utc, "end_at_utc"),
        asset_ids=tuple(spec.asset_ids),
        data_version=_text(spec.data_version, "data_version"),
        source_registry_version=_text(
            spec.source_registry_version,
            "source_registry_version",
        ),
        product_registry_version=_text(
            spec.product_registry_version,
            "product_registry_version",
        ),
        calendar_version=_text(
            spec.calendar_version,
            "calendar_version",
        ),
        pit=True,
        missing_data_policy=_text(
            spec.missing_data_policy,
            "missing_data_policy",
        ),
        content_hash=_ZERO_HASH,
    )


def _record_from_row(
    *,
    dataset_snapshot_id: str,
    manifest_source_ref: str,
    row: Mapping[str, object],
) -> ResearchBarRecord:
    if not isinstance(row, Mapping):
        raise ValueError("research bar row must be a mapping")

    asset_id = _text(row.get("asset_id"), "asset_id")
    interval_seconds = _positive_int(
        row.get("interval_seconds"),
        "interval_seconds",
    )
    bucket_open_utc = _utc(
        row.get("bucket_open_utc"),
        "bucket_open_utc",
    )
    bucket_close_utc = _utc(
        row.get("bucket_close_utc"),
        "bucket_close_utc",
    )
    available_at_utc = _utc(
        row.get("available_at_utc"),
        "available_at_utc",
    )
    source_id = _text(row.get("source_id"), "source_id")
    source_data_version = _text(
        row.get("source_data_version"),
        "source_data_version",
    )
    source_ref = _text(
        row.get("source_ref", manifest_source_ref),
        "source_ref",
    )
    open_ = _number(row.get("open"), "open")
    high = _number(row.get("high"), "high")
    low = _number(row.get("low"), "low")
    close = _number(row.get("close"), "close")
    volume = _number(row.get("volume"), "volume")

    canonical = _canonical_bar_payload(
        dataset_snapshot_id=dataset_snapshot_id,
        asset_id=asset_id,
        interval_seconds=interval_seconds,
        bucket_open_utc=bucket_open_utc,
        bucket_close_utc=bucket_close_utc,
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source_id=source_id,
        source_data_version=source_data_version,
        source_ref=source_ref,
        available_at_utc=available_at_utc,
    )
    return ResearchBarRecord(
        research_bar_id=research_bar_id(canonical),
        dataset_snapshot_id=dataset_snapshot_id,
        asset_id=asset_id,
        interval_seconds=interval_seconds,
        bucket_open_utc=bucket_open_utc,
        bucket_close_utc=bucket_close_utc,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source_id=source_id,
        source_data_version=source_data_version,
        source_ref=source_ref,
        available_at_utc=available_at_utc,
    )


def assemble_research_bar_manifest(
    *,
    source_ref: str,
    dataset_spec: ResearchDatasetSpec,
    bar_rows: tuple[Mapping[str, object], ...],
) -> ResearchBarManifestAssembly:
    """Build one deterministic, fully validated immutable research manifest."""
    source = _text(source_ref, "source_ref")
    if not isinstance(bar_rows, tuple) or not bar_rows:
        raise ValueError("bar_rows must be a non-empty immutable tuple")

    provisional = _provisional_snapshot(dataset_spec)
    records = tuple(
        _record_from_row(
            dataset_snapshot_id=provisional.dataset_snapshot_id,
            manifest_source_ref=source,
            row=row,
        )
        for row in bar_rows
    )
    ordered = tuple(
        sorted(
            records,
            key=lambda row: (
                row.asset_id,
                row.interval_seconds,
                row.bucket_open_utc,
                row.bucket_close_utc,
                row.source_id,
                row.research_bar_id,
            ),
        )
    )
    content_hash = research_dataset_content_hash(
        provisional,
        ordered,
    )
    snapshot = ResearchDatasetSnapshot(
        dataset_snapshot_id=provisional.dataset_snapshot_id,
        created_at_utc=provisional.created_at_utc,
        as_of_utc=provisional.as_of_utc,
        start_at_utc=provisional.start_at_utc,
        end_at_utc=provisional.end_at_utc,
        asset_ids=provisional.asset_ids,
        data_version=provisional.data_version,
        source_registry_version=provisional.source_registry_version,
        product_registry_version=provisional.product_registry_version,
        calendar_version=provisional.calendar_version,
        pit=True,
        missing_data_policy=provisional.missing_data_policy,
        content_hash=content_hash,
    )
    manifest = ResearchBarManifest(
        manifest_version=RESEARCH_BAR_MANIFEST_VERSION,
        source_ref=source,
        snapshot=snapshot,
        bars=ordered,
    )
    report = validate_research_bar_manifest(manifest)
    if research_dataset_content_hash(snapshot, ordered) != content_hash:
        raise ValueError("research dataset content hash is not deterministic")
    return ResearchBarManifestAssembly(
        manifest=manifest,
        validation_report=report,
    )
