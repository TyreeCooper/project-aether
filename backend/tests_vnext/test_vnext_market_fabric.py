from __future__ import annotations

from datetime import datetime, timezone

from app.vnext_market_fabric import build_market_fabric_runtime_snapshot


UTC = timezone.utc


def test_runtime_snapshot_keeps_executable_and_evidence_price_domains_separate() -> None:
    payload = build_market_fabric_runtime_snapshot(
        ingress_status={
            "enabled": True,
            "running": True,
            "cycle_count": 10,
            "last_error": None,
            "last_result": {
                "quotes": [
                    {
                        "asset_id": "btc",
                        "source_id": "kraken_public",
                        "venue": "Kraken",
                        "bid": 100000.0,
                        "ask": 100002.0,
                        "last": 100001.0,
                        "mark": 100001.0,
                        "reference_ts_utc": "2026-10-04T08:00:00+00:00",
                    }
                ]
            },
        },
        tape_snapshot={
            "runtime": {"running": True},
            "assets": [
                {
                    "asset_id": "btc",
                    "state": "FULL",
                    "composite_id": "cmp-1",
                    "composite_mark": 99950.0,
                    "source_count": 3,
                    "accepted_source_ids": [
                        "kraken_public_tape",
                        "coinbase_exchange_tape",
                        "gemini_public_tape",
                    ],
                    "quorum_required": 3,
                    "agreement_bps": 1.2,
                    "provenance_complete": True,
                }
            ],
        },
        as_of_utc=datetime(2026, 10, 4, 8, 0, 1, tzinfo=UTC),
    )

    row = payload["instruments"][0]
    assert row["executable"]["bid"] == 100000.0
    assert row["executable"]["ask"] == 100002.0
    assert row["intelligence"]["derived_reference_mark"] == 99950.0
    assert row["intelligence"]["derived_reference_executable"] is False
    assert row["intelligence"]["declared_independence_group_count"] == 3
    assert row["intelligence"]["empirical_independence_group_count"] is None
    assert len(row["intelligence"]["source_identities"]) == 3
    assert payload["runtime_contract"]["declared_independence_runtime"] == "BOUND"
    assert payload["runtime_contract"]["empirical_independence_runtime"] == "NOT_OBSERVED"
    assert payload["authority"]["consensus_can_replace_executable_price"] is False
    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True


def test_runtime_snapshot_preserves_not_observed_without_inventing_prices() -> None:
    payload = build_market_fabric_runtime_snapshot(
        ingress_status={
            "enabled": True,
            "running": True,
            "cycle_count": 1,
            "last_error": None,
            "last_result": {"quotes": []},
        },
        tape_snapshot={
            "runtime": {"running": True},
            "assets": [
                {
                    "asset_id": "eth",
                    "state": "DEGRADED",
                    "composite_id": "cmp-eth",
                    "composite_mark": 4500.0,
                    "source_count": 2,
                    "accepted_source_ids": [
                        "kraken_public_tape",
                        "coinbase_exchange_tape",
                    ],
                    "quorum_required": 3,
                    "agreement_bps": 3.0,
                    "provenance_complete": True,
                }
            ],
        },
        as_of_utc=datetime(2026, 10, 4, 8, 0, 1, tzinfo=UTC),
    )

    row = payload["instruments"][0]
    assert row["executable"]["state"] == "NOT_OBSERVED"
    assert row["executable"]["bid"] is None
    assert row["executable"]["ask"] is None
    assert row["intelligence"]["derived_reference_mark"] == 4500.0
    assert row["intelligence"]["derived_reference_executable"] is False
