from app.community import analyze_posts


def test_community_analysis_is_shadow_only_and_transparent():
    out = analyze_posts(
        "eth",
        [
            {"title": "Major upgrade and adoption growth", "score": 20, "comments": 5},
            {"title": "Outage risk warning", "score": 4, "comments": 2},
        ],
    )
    assert out["status"] == "shadow"
    assert out["shadow_only"] is True
    assert out["trade_influence_enabled"] is False
    assert out["posts_analyzed"] == 2
    assert out["sentiment_confidence"] == "low"
    assert out["narratives"]
