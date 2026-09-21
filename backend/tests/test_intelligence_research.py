from datetime import datetime, timedelta, timezone

from app.intelligence_research import observation_reaction, research_observations


BASE = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def snaps(prices):
    return [
        {
            "ts": (BASE + timedelta(minutes=offset)).isoformat(),
            "price_usd": price,
        }
        for offset, price in prices
    ]


def test_signal_before_threshold_move_is_classified_leading():
    rows = snaps([
        (-60, 100.0),
        (0, 100.0),
        (5, 100.1),
        (10, 100.2),
        (15, 100.7),
        (30, 101.0),
        (60, 101.2),
        (240, 102.0),
    ])
    obs = {
        "first_seen_at": BASE.isoformat(),
        "source_type": "community",
        "source_name": "r/example",
    }
    out = observation_reaction(rows, obs, threshold_pct=0.5)
    assert out["classification"] == "leading"
    assert out["first_threshold_move_at"] == (
        BASE + timedelta(minutes=15)
    ).isoformat()
    assert out["forward"]["30m_return_pct"] == 1.0


def test_signal_after_existing_move_is_classified_reactive():
    rows = snaps([
        (-60, 99.0),
        (0, 100.0),
        (5, 100.1),
        (30, 100.2),
        (60, 100.3),
        (240, 100.4),
    ])
    obs = {"first_seen_at": BASE.isoformat(), "source_type": "news"}
    out = observation_reaction(rows, obs, threshold_pct=0.5)
    assert out["classification"] == "reactive"
    assert out["prior_60m_return_pct"] > 0.5


def test_research_summary_never_enables_trade_influence():
    rows = snaps([(-60, 100.0), (0, 100.0), (30, 100.1), (240, 100.2)])
    obs = [{"first_seen_at": BASE.isoformat(), "source_type": "news"}]
    out = research_observations(rows, obs)
    assert out["trade_influence_enabled"] is False
    assert out["observations"] == 1
