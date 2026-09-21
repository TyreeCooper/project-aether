from datetime import datetime, timezone

from app.events import active_risk, normalize_event


def test_high_impact_us_event_creates_restricted_window():
    event = normalize_event(
        {
            "title": "CPI m/m",
            "country": "USD",
            "date": "2026-09-22T08:30:00-04:00",
            "impact": "High",
            "forecast": "0.2%",
            "previous": "0.3%",
        }
    )
    assert event is not None
    assert event["state"] == "restricted"
    assert event["window_before_min"] == 15
    assert event["window_after_min"] == 30
    assert event["verified_official"] is False


def test_active_risk_blocks_new_entries_inside_restricted_window():
    event = normalize_event(
        {
            "title": "FOMC Rate Decision",
            "country": "USD",
            "date": "2026-09-22T14:00:00-04:00",
            "impact": "High",
        }
    )
    assert event is not None
    now = datetime(2026, 9, 22, 18, 5, tzinfo=timezone.utc)
    state = active_risk([event], now=now)
    assert state["state"] == "restricted"
    assert state["new_entries_allowed"] is False


def test_non_us_low_event_does_not_create_crypto_blackout():
    event = normalize_event(
        {
            "title": "Minor Survey",
            "country": "EUR",
            "date": "2026-09-22T10:00:00-04:00",
            "impact": "Low",
        }
    )
    assert event is not None
    assert event["state"] == "normal"
