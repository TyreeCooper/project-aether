from app.reconciliation import ReconciliationService


def test_reconciliation_accepts_position_within_tolerance():
    service = ReconciliationService(tolerance_btc=1e-6)

    result = service.compare_position(
        local_btc=0.01,
        venue_btc=0.0100005,
    )

    assert result.ok is True
    assert result.reason == "matched"


def test_reconciliation_rejects_position_mismatch():
    service = ReconciliationService(tolerance_btc=1e-8)

    result = service.compare_position(
        local_btc=0.01,
        venue_btc=0.011,
    )

    assert result.ok is False
    assert result.reason == "position_mismatch"
    assert round(result.delta_btc, 6) == 0.001
