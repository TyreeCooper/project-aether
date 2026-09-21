from app.news import analyze_articles, cluster_articles


def test_news_context_is_shadow_only_and_requires_corroboration():
    out = analyze_articles(
        "sol",
        [
            {
                "title": "Solana upgrade drives adoption discussion",
                "domain": "example.com",
            },
            {
                "title": "Solana upgrade gains developer attention",
                "domain": "example.org",
            },
        ],
    )
    assert out["status"] == "shadow"
    assert out["trade_influence_enabled"] is False
    assert out["claims_verified"] is False
    assert out["articles_analyzed"] == 2
    assert out["independent_domains"] == 2
    assert out["narratives"]


def test_duplicate_news_is_clustered_before_corroboration():
    rows = [
        {
            "title": "Solana protocol upgrade scheduled for mainnet",
            "domain": "site-a.example",
            "seen_at": "2026-09-21T12:00:00+00:00",
        },
        {
            "title": "Solana protocol upgrade scheduled for mainnet today",
            "domain": "site-b.example",
            "seen_at": "2026-09-21T12:02:00+00:00",
        },
        {
            "title": "Solana price analysis and market outlook",
            "domain": "site-c.example",
            "seen_at": "2026-09-21T12:03:00+00:00",
        },
    ]
    clusters = cluster_articles(rows)
    assert len(clusters) == 2
    corroborated = [row for row in clusters if row["corroborated"]]
    assert len(corroborated) == 1
    assert corroborated[0]["independent_domains"] == 2

    out = analyze_articles("sol", rows)
    assert out["unique_story_clusters"] == 2
    assert out["corroborated_story_clusters"] == 1
    assert out["claims_verified"] is False
    assert out["verification_state"] == "corroborated_unverified"
