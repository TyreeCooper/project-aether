from app.official_macro import parse_bls_ics, verify_bls_event


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261013T083000
SUMMARY:Consumer Price Index for September 2026
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261002T083000
SUMMARY:Employment Situation for September 2026
END:VEVENT
END:VCALENDAR
"""


def test_bls_ics_parses_official_eastern_release_time_to_utc():
    rows = parse_bls_ics(ICS)
    assert len(rows) == 2
    cpi = next(row for row in rows if "Consumer Price" in row["title"])
    assert cpi["scheduled_at"] == "2026-10-13T12:30:00+00:00"


def test_forex_factory_cpi_must_match_primary_bls_schedule():
    official = parse_bls_ics(ICS)
    event = {
        "title": "CPI m/m",
        "country": "USD",
        "scheduled_at": "2026-10-13T12:30:00+00:00",
        "verified_official": False,
    }
    out = verify_bls_event(event, official)
    assert out["verified_official"] is True
    assert out["official_verification_status"] == "matched_primary_schedule"


def test_mismatched_time_never_receives_official_verification():
    official = parse_bls_ics(ICS)
    event = {
        "title": "CPI m/m",
        "country": "USD",
        "scheduled_at": "2026-10-13T13:30:00+00:00",
        "verified_official": False,
    }
    out = verify_bls_event(event, official)
    assert out["verified_official"] is False
    assert out["official_verification_status"] == "official_schedule_mismatch"
