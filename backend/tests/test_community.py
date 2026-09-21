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


def test_duplicate_pump_messages_raise_coordination_risk_without_becoming_signal():
    posts = [
        {"title": "SOL 100x moon pump", "score": 1, "comments": 0, "author": "a"},
        {"title": "SOL 100x moon pump", "score": 1, "comments": 0, "author": "a"},
        {"title": "SOL 100x moon pump", "score": 1, "comments": 0, "author": "b"},
        {"title": "Unconfirmed SOL rumor", "score": 1, "comments": 0, "author": "c"},
    ]
    out = analyze_posts("sol", posts)
    manipulation = out["manipulation"]
    assert manipulation["coordination_risk"] in {"medium", "high"}
    assert manipulation["duplicate_message_ratio"] > 0.5
    assert manipulation["pump_language_ratio"] > 0
    assert manipulation["rumor_intensity"] > 0
    assert out["trade_influence_enabled"] is False
