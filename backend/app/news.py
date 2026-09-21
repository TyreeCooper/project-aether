"""Asset-specific news context for Aether shadow intelligence.

Uses the public GDELT document API as a discovery aggregator. Headlines are
unverified context until corroborated by an official or primary source. This
module cannot create orders.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

import httpx

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
STOP = {
    "the", "and", "for", "with", "from", "that", "this", "into", "after", "over",
    "crypto", "cryptocurrency", "price", "market", "markets", "says", "amid",
}


def _tokens(text: str) -> list[str]:
    return [
        x.lower()
        for x in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        if x.lower() not in STOP
    ]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _title_token_set(title: str) -> set[str]:
    return set(_tokens(title))


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def cluster_articles(
    articles: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.55,
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "")
        tokens = _title_token_set(title)
        if not tokens:
            continue
        best_index = None
        best_score = 0.0
        for index, cluster in enumerate(clusters):
            score = _jaccard(tokens, set(cluster["_tokens"]))
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is None or best_score < similarity_threshold:
            clusters.append(
                {
                    "representative_title": title,
                    "_tokens": sorted(tokens),
                    "articles": [article],
                }
            )
        else:
            clusters[best_index]["articles"].append(article)
            clusters[best_index]["_tokens"] = sorted(
                set(clusters[best_index]["_tokens"]) | tokens
            )

    out: list[dict[str, Any]] = []
    for cluster in clusters:
        rows = list(cluster["articles"])
        domains = sorted(
            {
                str(row.get("domain") or "")
                for row in rows
                if str(row.get("domain") or "")
            }
        )
        seen = sorted(
            str(row.get("seen_at") or "")
            for row in rows
            if row.get("seen_at")
        )
        out.append(
            {
                "representative_title": cluster["representative_title"],
                "article_count": len(rows),
                "independent_domains": len(domains),
                "domains": domains,
                "first_seen_at": seen[0] if seen else None,
                "last_seen_at": seen[-1] if seen else None,
                "corroborated": len(domains) >= 2,
            }
        )
    out.sort(
        key=lambda row: (
            bool(row.get("corroborated")),
            int(row.get("independent_domains") or 0),
            int(row.get("article_count") or 0),
        ),
        reverse=True,
    )
    return out


def analyze_articles(asset_id: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
    terms: list[str] = []
    domains: set[str] = set()
    for row in articles:
        terms.extend(_tokens(str(row.get("title") or "")))
        domain = str(row.get("domain") or "")
        if domain:
            domains.add(domain)
    narratives = [
        {"term": term, "mentions": count}
        for term, count in Counter(terms).most_common(8)
    ]
    story_clusters = cluster_articles(articles)
    corroborated = [
        row for row in story_clusters
        if bool(row.get("corroborated"))
    ]
    return {
        "asset_id": asset_id,
        "status": "shadow" if articles else "unavailable",
        "shadow_only": True,
        "trade_influence_enabled": False,
        "articles_analyzed": len(articles),
        "independent_domains": len(domains),
        "unique_story_clusters": len(story_clusters),
        "corroborated_story_clusters": len(corroborated),
        "verification_state": (
            "corroborated_unverified"
            if corroborated
            else "unconfirmed"
            if articles
            else "unavailable"
        ),
        "story_clusters": story_clusters[:10],
        "narratives": narratives,
        "articles": articles[:10],
        "claims_verified": False,
        "note": (
            "Near-duplicate headlines are collapsed into story clusters. Cross-domain corroboration is not the same as primary-source verification."
            if articles
            else "No asset-specific news context is currently available."
        ),
    }


async def fetch_asset_news(
    asset_id: str,
    *,
    name: str,
    symbol: str,
    limit: int = 25,
) -> dict[str, Any]:
    asset_name = str(name or symbol or asset_id).strip()
    sym = str(symbol or "").strip().upper()
    query = f'"{asset_name}" crypto'
    if sym and sym.lower() != asset_name.lower():
        query = f'("{asset_name}" OR "{sym}") crypto'
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": max(5, min(int(limit), 50)),
        "format": "json",
        "sort": "HybridRel",
        "timespan": "1d",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(GDELT_DOC, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "asset_id": asset_id,
            "status": "degraded",
            "shadow_only": True,
            "trade_influence_enabled": False,
            "error": type(exc).__name__,
            "note": "News discovery feed unavailable; missing data is not treated as neutral.",
        }

    raw = payload.get("articles") if isinstance(payload, dict) else []
    articles: list[dict[str, Any]] = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        seen = row.get("seendate")
        seen_iso = None
        if seen:
            try:
                parsed = datetime.strptime(str(seen), "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc
                )
                seen_iso = parsed.isoformat()
            except ValueError:
                seen_iso = str(seen)
        articles.append(
            {
                "title": title,
                "url": url,
                "domain": _domain(url),
                "seen_at": seen_iso,
                "language": row.get("language"),
                "source_country": row.get("sourcecountry"),
                "verified_official": False,
            }
        )
    return analyze_articles(asset_id, articles)
