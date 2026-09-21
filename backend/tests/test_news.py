from app.news import analyze_articles


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
