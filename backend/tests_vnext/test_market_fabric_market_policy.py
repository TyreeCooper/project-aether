from __future__ import annotations

from aether_vnext.market_fabric_market_policy import (
    MarketClass,
    ReferenceDataEvent,
    market_policy,
    validate_reference_coverage,
)


def test_market_classes_do_not_share_one_undifferentiated_policy() -> None:
    crypto = market_policy(
        policy_version="crypto-v1",
        market_class=MarketClass.CRYPTO,
        witness_policy_bound=True,
        liveness_policy_bound=True,
    )
    futures = market_policy(
        policy_version="futures-v1",
        market_class=MarketClass.FUTURES,
        witness_policy_bound=True,
        liveness_policy_bound=True,
    )

    assert crypto.session_model == "24x7"
    assert futures.session_model == "exchange_calendar"
    assert crypto.requires_sequence is False
    assert futures.requires_sequence is True
    assert "roll_mapping" not in crypto.requires_reference_data
    assert "roll_mapping" in futures.requires_reference_data


def test_unbound_policy_fails_closed_instead_of_guessing_thresholds() -> None:
    equities = market_policy(
        policy_version="equity-v1",
        market_class=MarketClass.EQUITIES,
        witness_policy_bound=False,
        liveness_policy_bound=True,
    )

    assert equities.operational is False
    assert equities.blockers == ("witness_policy_unbound",)


def test_reference_coverage_reports_exact_missing_lifecycle_facts() -> None:
    futures = market_policy(
        policy_version="futures-v1",
        market_class=MarketClass.FUTURES,
        witness_policy_bound=True,
        liveness_policy_bound=True,
    )
    passed, missing = validate_reference_coverage(
        policy=futures,
        observed_event_types={
            "instrument_definition",
            "contract_expiry",
            "trading_session",
        },
    )

    assert passed is False
    assert "roll_mapping" in missing
    assert "trade_correction" in missing


def test_reference_event_is_versioned_and_replayable() -> None:
    event = ReferenceDataEvent(
        event_id="ref-1",
        instrument_id="MESZ6",
        market_class=MarketClass.FUTURES,
        reference_version="cme-ref-2026-10-04",
        event_type="contract_expiry",
        effective_from="2026-12-18T00:00:00Z",
        payload={"expiry": "2026-12-18"},
    )

    assert event.reference_version == "cme-ref-2026-10-04"
    assert event.payload["expiry"] == "2026-12-18"
