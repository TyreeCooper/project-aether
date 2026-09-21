"""Per-asset intelligence source registry.

Source discovery/ingestion and source trust are intentionally separate. A source
may be observed in shadow mode while still being a candidate. Only an operator
may promote a source to trusted, and that trust state still does not grant order
authority.
"""
from __future__ import annotations

from typing import Any

from app.community import SUBREDDITS

TRUST_STATES = {"candidate", "trusted", "untrusted", "disabled"}


def reddit_source(asset_id: str, subreddit: str) -> dict[str, Any]:
    asset = str(asset_id).lower()
    sub = str(subreddit).strip()
    return {
        "source_id": f"{asset}:reddit:{sub.lower()}",
        "asset_id": asset,
        "source_type": "community",
        "platform": "reddit",
        "name": f"r/{sub}",
        "url": f"https://www.reddit.com/r/{sub}/",
        "tier": "B",
        "trust_state": "candidate",
        "origin": "curated_seed",
        "ingestion_mode": "shadow",
        "trade_influence_enabled": False,
        "note": "Configured for shadow observation; operator trust is a separate state.",
    }


def seed_asset_sources(asset_ids: list[str] | tuple[str, ...] | set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in asset_ids:
        asset_id = str(raw).lower()
        subreddit = SUBREDDITS.get(asset_id)
        if subreddit:
            rows.append(reddit_source(asset_id, subreddit))
    return rows


def merge_source_registry(
    existing: list[dict[str, Any]] | None,
    asset_ids: list[str] | tuple[str, ...] | set[str],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "")
        if source_id:
            by_id[source_id] = dict(row)
    for seed in seed_asset_sources(asset_ids):
        source_id = str(seed["source_id"])
        if source_id not in by_id:
            by_id[source_id] = seed
    return sorted(
        by_id.values(),
        key=lambda row: (
            str(row.get("asset_id") or ""),
            str(row.get("source_type") or ""),
            str(row.get("name") or ""),
        ),
    )


def set_trust_state(
    registry: list[dict[str, Any]],
    source_id: str,
    state: str,
) -> list[dict[str, Any]]:
    new_state = str(state).lower().strip()
    if new_state not in TRUST_STATES:
        raise ValueError(f"invalid trust state: {new_state}")
    found = False
    rows: list[dict[str, Any]] = []
    for row in registry:
        item = dict(row)
        if str(item.get("source_id") or "") == str(source_id):
            item["trust_state"] = new_state
            found = True
        rows.append(item)
    if not found:
        raise KeyError(source_id)
    return rows


def registry_summary(registry: list[dict[str, Any]]) -> dict[str, Any]:
    states = {state: 0 for state in sorted(TRUST_STATES)}
    assets: set[str] = set()
    for row in registry:
        state = str(row.get("trust_state") or "candidate")
        states[state] = states.get(state, 0) + 1
        asset = str(row.get("asset_id") or "")
        if asset:
            assets.add(asset)
    return {
        "sources": len(registry),
        "assets": len(assets),
        "trust_states": states,
        "trade_influence_enabled": False,
        "note": "Trust governs evidence handling only; it does not grant order authority.",
    }
