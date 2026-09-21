"""Community-intelligence shadow feed.

Community data is context only. It is never a direct order signal. Claims from
social sources are treated as unverified unless separately corroborated.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any

import httpx

SUBREDDITS: dict[str, str] = {
    "btc": "Bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "xrp": "XRP",
    "bnb": "bnbchainofficial",
    "ada": "cardano",
    "link": "Chainlink",
    "avax": "Avax",
    "sui": "sui",
}

POSITIVE = {
    "adoption", "upgrade", "growth", "bullish", "breakout", "launch", "partnership",
    "approved", "approval", "win", "winning", "rally", "surge", "strong", "record",
}
NEGATIVE = {
    "exploit", "hack", "outage", "bearish", "crash", "dump", "scam", "lawsuit",
    "delay", "failed", "failure", "risk", "selloff", "down", "weak", "warning",
}
STOP = {
    "the", "and", "for", "that", "with", "this", "from", "what", "about", "have",
    "your", "you", "are", "was", "will", "just", "into", "why", "how", "can",
    "crypto", "coin", "token", "price", "market",
}
PUMP_TERMS = {
    "100x", "1000x", "moon", "mooning", "pump", "ape", "lambo", "guaranteed",
    "sendit", "buybuybuy", "rocket",
}
RUMOR_TERMS = {
    "rumor", "rumour", "unconfirmed", "leak", "leaked", "alleged", "apparently",
    "hearing", "speculation",
}


def _tokens(text: str) -> list[str]:
    return [x.lower() for x in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", text)]


def _fingerprint(text: str) -> str:
    tokens = [x for x in _tokens(text) if x not in STOP]
    return " ".join(tokens)


def _coordination_metrics(posts: list[dict[str, Any]]) -> dict[str, Any]:
    fingerprints = [
        _fingerprint(str(post.get("title") or ""))
        for post in posts
    ]
    fingerprints = [value for value in fingerprints if value]
    counts = Counter(fingerprints)
    duplicated = sum(count for count in counts.values() if count > 1)
    duplicate_ratio = duplicated / len(fingerprints) if fingerprints else 0.0

    pump_hits = 0
    rumor_hits = 0
    for post in posts:
        tokens = set(_tokens(str(post.get("title") or "")))
        pump_hits += len(tokens & PUMP_TERMS)
        rumor_hits += len(tokens & RUMOR_TERMS)
    pump_ratio = min(pump_hits / max(len(posts), 1), 1.0)
    rumor_ratio = min(rumor_hits / max(len(posts), 1), 1.0)

    authors = [
        str(post.get("author") or "").strip().lower()
        for post in posts
        if str(post.get("author") or "").strip()
    ]
    unique_authors = len(set(authors))
    author_concentration = (
        1 - unique_authors / len(authors)
        if authors
        else None
    )

    score = duplicate_ratio * 60 + pump_ratio * 25
    if author_concentration is not None:
        score += max(author_concentration, 0.0) * 15
    score = round(min(max(score, 0.0), 100.0), 2)
    state = "high" if score >= 60 else "medium" if score >= 30 else "low"
    return {
        "coordination_risk": state,
        "manipulation_risk_score": score,
        "duplicate_message_ratio": round(duplicate_ratio, 4),
        "pump_language_ratio": round(pump_ratio, 4),
        "rumor_intensity": round(rumor_ratio * 100, 2),
        "unique_authors": unique_authors if authors else None,
        "author_concentration": (
            None
            if author_concentration is None
            else round(author_concentration, 4)
        ),
        "method": "transparent_community_manipulation_heuristic_v1",
        "note": "Heuristic risk indicators are not proof of bots or coordinated manipulation.",
    }


def analyze_posts(asset_id: str, posts: list[dict[str, Any]]) -> dict[str, Any]:
    words: list[str] = []
    positive = negative = 0
    engagement = 0
    newest = None
    for post in posts:
        title = str(post.get("title") or "")
        tokens = _tokens(title)
        words.extend(x for x in tokens if x not in STOP)
        positive += sum(1 for x in tokens if x in POSITIVE)
        negative += sum(1 for x in tokens if x in NEGATIVE)
        engagement += int(post.get("score") or 0) + int(post.get("comments") or 0)
        ts = post.get("created_at")
        if ts and (newest is None or str(ts) > str(newest)):
            newest = ts
    denom = positive + negative
    sentiment = round((positive - negative) / denom * 100, 2) if denom else 0.0
    narratives = [
        {"term": term, "mentions": count}
        for term, count in Counter(words).most_common(6)
    ]
    return {
        "asset_id": asset_id,
        "status": "shadow",
        "shadow_only": True,
        "posts_analyzed": len(posts),
        "sentiment": sentiment,
        "sentiment_method": "transparent_title_lexicon_v1",
        "sentiment_confidence": "low",
        "engagement": engagement,
        "discussion_volume_ratio": None,
        "narratives": narratives,
        "newest_post_at": newest,
        "manipulation": _coordination_metrics(posts),
        "source_tier": "B",
        "claims_verified": False,
        "trade_influence_enabled": False,
        "note": "Community context is unverified and cannot directly create an order.",
    }


async def fetch_reddit(asset_id: str, limit: int = 25) -> dict[str, Any]:
    subreddit = SUBREDDITS.get(str(asset_id).lower())
    if not subreddit:
        return {
            "asset_id": asset_id,
            "status": "unavailable",
            "shadow_only": True,
            "source": None,
            "note": "No verified community source bundle is configured for this asset yet.",
        }
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    headers = {"User-Agent": "Project-Aether/1.0 community-shadow"}
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(url, params={"limit": max(5, min(limit, 50))}, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "asset_id": asset_id,
            "status": "degraded",
            "shadow_only": True,
            "source": f"r/{subreddit}",
            "error": type(exc).__name__,
            "note": "Community feed unavailable; this is not interpreted as neutral sentiment.",
        }
    children = (((payload or {}).get("data") or {}).get("children") or [])
    posts: list[dict[str, Any]] = []
    for child in children:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        created = data.get("created_utc")
        created_iso = None
        try:
            created_iso = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
        posts.append(
            {
                "title": str(data.get("title") or ""),
                "score": int(data.get("score") or 0),
                "comments": int(data.get("num_comments") or 0),
                "created_at": created_iso,
                "permalink": str(data.get("permalink") or ""),
                "author": str(data.get("author") or ""),
            }
        )
    out = analyze_posts(asset_id, posts)
    out["source"] = f"r/{subreddit}"
    out["source_url"] = f"https://www.reddit.com/r/{subreddit}/"
    out["posts"] = posts[:10]
    return out
