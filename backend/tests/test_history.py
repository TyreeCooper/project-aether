from app.db import DatabaseStore


def test_row_to_dict_serializes_datetime():
    from datetime import datetime, timezone

    class FakeRecord(dict):
        pass

    row = FakeRecord(
        ts=datetime(2026, 9, 20, 20, 54, tzinfo=timezone.utc),
        value=7,
    )
    out = DatabaseStore._row_to_dict(row)
    assert out["ts"] == "2026-09-20T20:54:00+00:00"
    assert out["value"] == 7
