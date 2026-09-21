from types import SimpleNamespace

from app.intelligence import asset_context, opportunity_24h, pearson_from_bars


def test_opportunity_24h_measures_range_without_calling_it_profit():
    out = opportunity_24h({"mark": 102, "open_24h": 100, "high_24h": 110, "low_24h": 90, "bid": 101.9, "ask": 102.1, "volume_24h": 500, "vwap_24h": 99, "trades_24h": 42})
    assert out["net_change_pct"] == 2.0
    assert out["opportunity_range"] == 20.0
    assert out["opportunity_range_pct"] == 20.0
    assert out["range_position_pct"] == 60.0
    assert "not guaranteed" in out["label"]


def test_pearson_from_bars_detects_aligned_returns():
    a = []
    b = []
    pa = 100.0
    pb = 200.0
    for i in range(50):
        pa *= 1.01 if i % 2 == 0 else 0.995
        pb *= 1.02 if i % 2 == 0 else 0.99
        ts = 1_700_000_000 + i * 60
        a.append({"ts": ts, "close": pa})
        b.append({"ts": ts, "close": pb})
    corr = pearson_from_bars(a, b)
    assert corr is not None
    assert corr > 0.9


def test_asset_context_preserves_shadow_feeds_and_news_is_only_candidate_evidence():
    book = SimpleNamespace(
        id="sol",
        symbol="SOL",
        pair="SOL/USD",
        bars=[],
        bars_1h=[],
        view=lambda: {
            "mark": 105,
            "open_24h": 100,
            "high_24h": 106,
            "low_24h": 98,
            "bid": 104.9,
            "ask": 105.1,
            "volume_24h": 1000,
            "trades_24h": 100,
        },
    )
    community = {
        "status": "shadow",
        "shadow_only": True,
        "trade_influence_enabled": False,
        "sentiment": 25.0,
        "narratives": [{"term": "upgrade", "mentions": 3}],
    }
    news = {
        "status": "shadow",
        "shadow_only": True,
        "trade_influence_enabled": False,
        "articles_analyzed": 4,
        "independent_domains": 3,
        "claims_verified": False,
        "narratives": [{"term": "upgrade", "mentions": 2}],
    }

    out = asset_context(
        book,
        [book],
        community=community,
        news=news,
    )

    assert out["community"] is community
    assert out["news"] is news
    news_drivers = [
        row for row in out["attribution"]["drivers"]
        if row.get("type") == "asset_news"
    ]
    assert len(news_drivers) == 1
    assert news_drivers[0]["evidence"]["claims_verified"] is False
    assert news["trade_influence_enabled"] is False
