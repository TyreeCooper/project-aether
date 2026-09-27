"""Read-only integrity checks for a persisted forward-paper campaign ledger."""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from aether_vnext.forward_paper import ForwardPaperRouteBaseline, parse_route_id
from aether_vnext.forward_paper_preflight import (
    forward_paper_baseline_snapshot_hash,
    forward_paper_campaign_route_id,
    forward_paper_route_baseline_hash,
)
from aether_vnext.store import VNextStore, canonical_payload_hash


def _stored_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def forward_paper_ledger_blockers(
    conn: Connection,
    *,
    store: VNextStore,
    campaign_id: str,
) -> tuple[str, ...]:
    """Return deterministic blockers for persisted burn-in ledger drift."""
    campaign_key = str(campaign_id).strip()
    if not campaign_key:
        raise ValueError("campaign_id is required")

    campaigns = store.tables["forward_paper_campaigns"]
    campaign = conn.execute(
        sa.select(campaigns).where(campaigns.c.campaign_id == campaign_key)
    ).mappings().first()
    if campaign is None:
        return ()

    blockers: list[str] = []
    route_table = store.tables["forward_paper_campaign_routes"]
    route_rows = tuple(
        conn.execute(
            sa.select(route_table)
            .where(route_table.c.campaign_id == campaign_key)
            .order_by(
                route_table.c.route_id.asc(),
                route_table.c.playbook_id.asc(),
                route_table.c.campaign_route_id.asc(),
            )
        ).mappings()
    )
    if not route_rows:
        return ("forward_paper_ledger:campaign_has_no_routes",)

    evidence = store.tables["evidence_windows"]
    provenance = store.tables["held_out_evidence_provenance"]
    runs = store.tables["backtest_runs"]
    datasets = store.tables["research_dataset_snapshots"]
    folds = store.tables["fold_results"]

    routes: list[ForwardPaperRouteBaseline] = []
    route_by_id: dict[str, dict[str, object]] = {}
    for row in route_rows:
        route_id = str(row["campaign_route_id"])
        route_by_id[route_id] = dict(row)
        if str(row["configuration_hash"]) != str(campaign["configuration_hash"]):
            blockers.append(
                f"forward_paper_ledger:route_configuration_mismatch:{route_id}"
            )
        try:
            route_baseline = ForwardPaperRouteBaseline(
                campaign_route_id=route_id,
                campaign_id=str(row["campaign_id"]),
                route_id=str(row["route_id"]),
                playbook_id=str(row["playbook_id"]),
                playbook_version=str(row["playbook_version"]),
                configuration_hash=str(row["configuration_hash"]),
                runtime_registry_binding_hash=str(
                    row["runtime_registry_binding_hash"]
                ),
                historical_validation_window_ids=tuple(
                    str(value)
                    for value in (
                        row["historical_validation_window_ids"] or ()
                    )
                ),
                historical_metrics_snapshot_hash=str(
                    row["historical_metrics_snapshot_hash"]
                ),
            )
            routes.append(route_baseline)

            expected_campaign_route_id = forward_paper_campaign_route_id(
                campaign_id=campaign_key,
                route_id=route_baseline.route_id,
                playbook_id=route_baseline.playbook_id,
                playbook_version=route_baseline.playbook_version,
                configuration_hash=route_baseline.configuration_hash,
                runtime_registry_binding_hash=(
                    route_baseline.runtime_registry_binding_hash
                ),
            )
            if expected_campaign_route_id != route_baseline.campaign_route_id:
                blockers.append(
                    "forward_paper_ledger:campaign_route_id_mismatch:"
                    f"{route_id}"
                )

            asset_id, _, _ = parse_route_id(route_baseline.route_id)
            try:
                current_runtime = store.load_runtime_registry_binding(
                    conn,
                    asset_id=asset_id,
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                blockers.append(
                    "forward_paper_ledger:runtime_binding_invalid:"
                    f"{route_id}"
                )
            else:
                if current_runtime is None:
                    blockers.append(
                        "forward_paper_ledger:runtime_binding_missing:"
                        f"{route_id}"
                    )
                else:
                    if (
                        str(current_runtime["configuration_hash"])
                        != route_baseline.configuration_hash
                    ):
                        blockers.append(
                            "forward_paper_ledger:"
                            "runtime_binding_configuration_mismatch:"
                            f"{route_id}"
                        )
                    if (
                        str(current_runtime["binding_hash"])
                        != route_baseline.runtime_registry_binding_hash
                    ):
                        blockers.append(
                            "forward_paper_ledger:runtime_binding_hash_mismatch:"
                            f"{route_id}"
                        )

            source_rows: list[dict[str, object]] = []
            hash_inputs_complete = True
            for window_id in route_baseline.historical_validation_window_ids:
                source = conn.execute(
                    sa.select(evidence).where(
                        evidence.c.evidence_window_id == window_id
                    )
                ).mappings().first()
                if source is None:
                    blockers.append(
                        "forward_paper_ledger:missing_historical_baseline:"
                        f"{route_id}:{window_id}"
                    )
                    hash_inputs_complete = False
                    continue

                prov = conn.execute(
                    sa.select(provenance).where(
                        provenance.c.evidence_window_id == window_id
                    )
                ).mappings().first()
                if prov is None:
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_baseline_provenance_missing:"
                        f"{route_id}:{window_id}"
                    )
                    hash_inputs_complete = False
                    continue

                if (
                    str(source["sample_domain"]) != "held_out"
                    or str(source["route_id"]) != route_baseline.route_id
                    or str(source["playbook_id"]) != route_baseline.playbook_id
                    or str(source["playbook_version"])
                    != route_baseline.playbook_version
                    or str(source["configuration_hash"])
                    != route_baseline.configuration_hash
                    or str(source["policy_version"])
                    != str(campaign["policy_version"])
                ):
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_baseline_family_mismatch:"
                        f"{route_id}:{window_id}"
                    )
                run_id = str(prov["backtest_run_id"])
                dataset_id = str(prov["dataset_snapshot_id"])
                fold_ids = tuple(
                    str(value).strip()
                    for value in (prov["fold_result_ids"] or ())
                )
                run = conn.execute(
                    sa.select(runs).where(
                        runs.c.backtest_run_id == run_id
                    )
                ).mappings().first()
                if run is None:
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_provenance_run_missing:"
                        f"{route_id}:{window_id}"
                    )
                elif (
                    str(run["run_type"]).strip().lower() != "held_out"
                    or run["finished_at_utc"] is None
                    or str(run["playbook_id"])
                    != route_baseline.playbook_id
                    or str(run["playbook_version"])
                    != route_baseline.playbook_version
                    or str(run["configuration_hash"])
                    != route_baseline.configuration_hash
                    or str(run["dataset_snapshot_id"]) != dataset_id
                ):
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_provenance_run_mismatch:"
                        f"{route_id}:{window_id}"
                    )
                dataset = conn.execute(
                    sa.select(datasets).where(
                        datasets.c.dataset_snapshot_id == dataset_id
                    )
                ).mappings().first()
                asset_id = route_baseline.route_id.split(":", 1)[0]
                if dataset is None:
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_provenance_dataset_missing:"
                        f"{route_id}:{window_id}"
                    )
                elif (
                    not bool(dataset["pit"])
                    or asset_id not in {
                        str(value).strip().lower()
                        for value in (dataset["asset_ids"] or ())
                    }
                ):
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_provenance_dataset_mismatch:"
                        f"{route_id}:{window_id}"
                    )

                selected = tuple(
                    dict(row)
                    for row in conn.execute(
                        sa.select(folds).where(
                            folds.c.fold_result_id.in_(fold_ids)
                        )
                    ).mappings()
                ) if fold_ids else ()
                fold_set_valid = bool(
                    fold_ids
                    and all(fold_ids)
                    and len(fold_ids) == len(set(fold_ids))
                    and len(selected) == len(fold_ids)
                    and all(
                        str(row["backtest_run_id"]) == run_id
                        for row in selected
                    )
                )
                if not fold_set_valid:
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_provenance_fold_mismatch:"
                        f"{route_id}:{window_id}"
                    )
                else:
                    ordered = tuple(
                        sorted(
                            selected,
                            key=lambda row: (
                                _stored_utc(row["test_start_utc"]),
                                _stored_utc(row["test_end_utc"]),
                                str(row["fold_result_id"]),
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
                        _stored_utc(row["test_start_utc"])
                        for row in ordered
                    )
                    last_test_at = max(
                        _stored_utc(row["test_end_utc"])
                        for row in ordered
                    )
                    contained = (
                        _stored_utc(source["first_timestamp_utc"])
                        >= first_test_at
                        and _stored_utc(source["last_timestamp_utc"])
                        <= last_test_at
                    )
                    if overlaps or not contained:
                        blockers.append(
                            "forward_paper_ledger:"
                            "historical_provenance_fold_window_mismatch:"
                            f"{route_id}:{window_id}"
                        )
                expected_provenance_hash = canonical_payload_hash(
                    {
                        "backtest_run_id": run_id,
                        "dataset_snapshot_id": dataset_id,
                        "fold_result_ids": sorted(fold_ids),
                        "route_id": str(source["route_id"]),
                        "playbook_id": str(source["playbook_id"]),
                        "playbook_version": str(source["playbook_version"]),
                        "configuration_hash": str(
                            source["configuration_hash"]
                        ),
                        "immutable_trade_ids": sorted(
                            str(value)
                            for value in (
                                source["immutable_trade_ids"] or ()
                            )
                        ),
                        "metrics_snapshot_hash": str(
                            source["metrics_snapshot_hash"]
                        ),
                    }
                )
                if expected_provenance_hash != str(prov["provenance_hash"]):
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_provenance_hash_mismatch:"
                        f"{route_id}:{window_id}"
                    )
                merged = dict(source)
                merged.update(
                    {
                        "backtest_run_id": prov["backtest_run_id"],
                        "dataset_snapshot_id": prov["dataset_snapshot_id"],
                        "fold_result_ids": prov["fold_result_ids"],
                        "provenance_hash": prov["provenance_hash"],
                    }
                )
                source_rows.append(merged)

            if (
                hash_inputs_complete
                and len(source_rows)
                == len(route_baseline.historical_validation_window_ids)
            ):
                source_hash = forward_paper_route_baseline_hash(
                    route_id=route_baseline.route_id,
                    playbook_id=route_baseline.playbook_id,
                    playbook_version=route_baseline.playbook_version,
                    configuration_hash=route_baseline.configuration_hash,
                    runtime_registry_binding_hash=(
                        route_baseline.runtime_registry_binding_hash
                    ),
                    rows=tuple(source_rows),
                )
                if (
                    source_hash
                    != route_baseline.historical_metrics_snapshot_hash
                ):
                    blockers.append(
                        "forward_paper_ledger:"
                        "historical_baseline_hash_mismatch:"
                        f"{route_id}"
                    )
        except (TypeError, ValueError):
            blockers.append(
                f"forward_paper_ledger:invalid_route_baseline:{route_id}"
            )

    if len(routes) == len(route_rows):
        persisted_hash = forward_paper_baseline_snapshot_hash(
            configuration_hash=str(campaign["configuration_hash"]),
            policy_version=str(campaign["policy_version"]),
            routes=tuple(routes),
        )
        if persisted_hash != str(campaign["baseline_snapshot_hash"]):
            blockers.append(
                "forward_paper_ledger:baseline_snapshot_mismatch"
            )

    links = store.tables["forward_paper_campaign_windows"]
    closed = store.tables["closed_trades"]
    lineage = store.tables["decision_lineage"]
    setups = store.tables["setups"]
    owned_route_ids = tuple(route_by_id)
    link_rows = tuple(
        conn.execute(
            sa.select(links)
            .where(
                sa.or_(
                    links.c.campaign_id == campaign_key,
                    links.c.campaign_route_id.in_(owned_route_ids),
                )
            )
            .order_by(links.c.campaign_window_id.asc())
        ).mappings()
    )
    for link in link_rows:
        campaign_window_id = str(link["campaign_window_id"])
        link_campaign_id = str(link["campaign_id"])
        campaign_route_id = str(link["campaign_route_id"])
        route = route_by_id.get(campaign_route_id)
        if route is None:
            referenced_route = conn.execute(
                sa.select(route_table).where(
                    route_table.c.campaign_route_id == campaign_route_id
                )
            ).mappings().first()
            if (
                referenced_route is not None
                and str(referenced_route["campaign_id"]) != campaign_key
            ):
                blockers.append(
                    "forward_paper_ledger:cross_campaign_route_link:"
                    f"{campaign_window_id}"
                )
            else:
                blockers.append(
                    "forward_paper_ledger:missing_campaign_route:"
                    f"{campaign_window_id}"
                )
            continue
        if (
            link_campaign_id != campaign_key
            or str(route["campaign_id"]) != campaign_key
        ):
            blockers.append(
                "forward_paper_ledger:cross_campaign_route_link:"
                f"{campaign_window_id}"
            )
            continue

        window_id = str(link["evidence_window_id"])
        window = conn.execute(
            sa.select(evidence).where(
                evidence.c.evidence_window_id == window_id
            )
        ).mappings().first()
        if window is None:
            blockers.append(
                f"forward_paper_ledger:missing_evidence_window:{window_id}"
            )
            continue

        linked_at = _stored_utc(link["linked_at_utc"])
        if linked_at < _stored_utc(campaign["started_at_utc"]):
            blockers.append(
                f"forward_paper_ledger:link_predates_campaign:{window_id}"
            )
        if linked_at < _stored_utc(window["last_timestamp_utc"]):
            blockers.append(
                f"forward_paper_ledger:link_predates_window_end:{window_id}"
            )
        if linked_at < _stored_utc(window["created_at_utc"]):
            blockers.append(
                f"forward_paper_ledger:link_predates_evidence_creation:{window_id}"
            )

        sample_domain_ok = str(window["sample_domain"]) == "paper_forward"
        if not sample_domain_ok:
            blockers.append(
                f"forward_paper_ledger:window_not_paper_forward:{window_id}"
            )

        family_ok = not (
            str(window["route_id"]) != str(route["route_id"])
            or str(window["playbook_id"]) != str(route["playbook_id"])
            or str(window["playbook_version"]) != str(route["playbook_version"])
            or str(window["configuration_hash"])
            != str(route["configuration_hash"])
            or str(window["policy_version"]) != str(campaign["policy_version"])
        )
        if not family_ok:
            blockers.append(
                f"forward_paper_ledger:window_family_mismatch:{window_id}"
            )

        starts_in_campaign = _stored_utc(
            window["first_timestamp_utc"]
        ) >= _stored_utc(campaign["started_at_utc"])
        if not starts_in_campaign:
            blockers.append(
                f"forward_paper_ledger:window_predates_campaign:{window_id}"
            )

        trade_ids = tuple(
            str(value).strip()
            for value in (window["immutable_trade_ids"] or ())
        )
        sample_shape_ok = bool(
            trade_ids
            and all(trade_ids)
            and len(trade_ids) == len(set(trade_ids))
            and int(window["n"]) == len(trade_ids)
        )
        if not sample_shape_ok:
            blockers.append(
                f"forward_paper_ledger:window_trade_sample_invalid:{window_id}"
            )

        if (
            sample_domain_ok
            and family_ok
            and starts_in_campaign
            and sample_shape_ok
        ):
            for trade_id in trade_ids:
                trade = conn.execute(
                    sa.select(
                        closed.c.trade_id,
                        closed.c.route_id,
                        closed.c.policy_version.label("closed_policy_version"),
                        closed.c.configuration_hash,
                        closed.c.closed_at_utc,
                        closed.c.firm_event_id.label("closed_firm_event_id"),
                        lineage.c.firm_event_id.label(
                            "lineage_firm_event_id"
                        ),
                        lineage.c.trade_id.label("lineage_trade_id"),
                        lineage.c.route_id.label("lineage_route_id"),
                        lineage.c.policy_version.label(
                            "lineage_policy_version"
                        ),
                        lineage.c.configuration_hash.label(
                            "lineage_configuration_hash"
                        ),
                        lineage.c.playbook_id.label("lineage_playbook_id"),
                        lineage.c.playbook_version.label(
                            "lineage_playbook_version"
                        ),
                        setups.c.firm_event_id.label(
                            "setup_firm_event_id"
                        ),
                        setups.c.route_id.label("setup_route_id"),
                        setups.c.policy_version.label("setup_policy_version"),
                        setups.c.configuration_hash.label(
                            "setup_configuration_hash"
                        ),
                        setups.c.playbook_id.label("setup_playbook_id"),
                        setups.c.playbook_version.label(
                            "setup_playbook_version"
                        ),
                        setups.c.trigger_bar_close_exchange_ts,
                    )
                    .select_from(
                        closed.join(
                            lineage,
                            closed.c.firm_event_id
                            == lineage.c.firm_event_id,
                        ).join(
                            setups,
                            lineage.c.setup_id == setups.c.setup_id,
                        )
                    )
                    .where(closed.c.trade_id == trade_id)
                ).mappings().first()
                if trade is None:
                    blockers.append(
                        "forward_paper_ledger:missing_closed_trade_lineage:"
                        f"{window_id}:{trade_id}"
                    )
                    continue
                if (
                    str(trade["route_id"]) != str(route["route_id"])
                    or str(trade["closed_policy_version"])
                    != str(campaign["policy_version"])
                    or str(trade["configuration_hash"])
                    != str(route["configuration_hash"])
                    or str(trade["lineage_firm_event_id"])
                    != str(trade["closed_firm_event_id"])
                    or str(trade["lineage_trade_id"]) != trade_id
                    or str(trade["setup_firm_event_id"])
                    != str(trade["closed_firm_event_id"])
                    or str(trade["lineage_route_id"])
                    != str(route["route_id"])
                    or str(trade["lineage_policy_version"])
                    != str(campaign["policy_version"])
                    or str(trade["lineage_configuration_hash"])
                    != str(route["configuration_hash"])
                    or str(trade["lineage_playbook_id"])
                    != str(route["playbook_id"])
                    or str(trade["lineage_playbook_version"])
                    != str(route["playbook_version"])
                    or str(trade["setup_route_id"])
                    != str(route["route_id"])
                    or str(trade["setup_policy_version"])
                    != str(campaign["policy_version"])
                    or str(trade["setup_configuration_hash"])
                    != str(route["configuration_hash"])
                    or str(trade["setup_playbook_id"])
                    != str(route["playbook_id"])
                    or str(trade["setup_playbook_version"])
                    != str(route["playbook_version"])
                ):
                    blockers.append(
                        "forward_paper_ledger:trade_lineage_mismatch:"
                        f"{window_id}:{trade_id}"
                    )
                trigger_ts = _stored_utc(
                    trade["trigger_bar_close_exchange_ts"]
                )
                closed_at = _stored_utc(trade["closed_at_utc"])
                if trigger_ts < _stored_utc(campaign["started_at_utc"]):
                    blockers.append(
                        "forward_paper_ledger:trade_setup_predates_campaign:"
                        f"{window_id}:{trade_id}"
                    )
                if closed_at < trigger_ts:
                    blockers.append(
                        "forward_paper_ledger:trade_closes_before_setup:"
                        f"{window_id}:{trade_id}"
                    )
                if closed_at > _stored_utc(window["created_at_utc"]):
                    blockers.append(
                        "forward_paper_ledger:evidence_predates_trade_close:"
                        f"{window_id}:{trade_id}"
                    )

    return tuple(dict.fromkeys(blockers))
