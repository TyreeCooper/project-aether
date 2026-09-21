import asyncio

from app.crypto_events import fetch_crypto_calendar, normalize_crypto_event


def test_estimated_crypto_event_never_invents_exact_blackout_timestamp():
    out = normalize_crypto_event(
        {
            "id": "evt-1",
            "title": "Protocol upgrade window",
            "date": "2026-10-31T12:00:00Z",
            "displayedDate": "By 31 Oct 2026",
            "dateType": "date",
            "isEstimated": True,
            "categories": ["Release"],
            "coins": [{"slug": "solana", "symbol": "sol", "name": "Solana"}],
            "impact": 7.5,
        }
    )
    assert out is not None
    assert out["is_estimated"] is True
    assert out["scheduled_at"] is None
    assert out["risk_window_enforced"] is False
    assert out["trade_influence_enabled"] is False


def test_exact_crypto_event_preserves_provider_timestamp_but_stays_observe_only():
    out = normalize_crypto_event(
        {
            "id": "evt-2",
            "title": "Mainnet activation",
            "date": "2026-10-12T14:00:00Z",
            "displayedDate": "12 Oct 2026",
            "dateType": "date",
            "isEstimated": False,
            "categories": ["Release"],
            "coins": [{"slug": "avalanche", "symbol": "avax", "name": "Avalanche"}],
            "sourceUrl": "https://example.org/official",
            "lastVerifiedAt": "2026-10-01T09:00:00Z",
        }
    )
    assert out is not None
    assert out["scheduled_at"] == "2026-10-12T14:00:00+00:00"
    assert out["proof_linked"] is True
    assert out["state"] == "observe"
    assert out["risk_window_enforced"] is False


def test_unconfigured_crypto_calendar_fails_closed_as_unavailable(monkeypatch):
    monkeypatch.delenv("COINMARKETCAL_API_KEY", raising=False)
    out = asyncio.run(fetch_crypto_calendar(["btc", "eth"]))
    assert out["configured"] is False
    assert out["connected"] is False
    assert out["events"] == []
    assert out["status"] == "unconfigured"
