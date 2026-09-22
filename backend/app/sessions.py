"""Market sessions and the clocks the desk actually uses.

Times are America/New_York (Atlanta). Crypto does not close.
The UI and the bot read this same object.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.playbooks import playbook_profile
from app.universe import BY_ID

ET = ZoneInfo("America/New_York")

# Inclusive start, exclusive end in minutes from midnight ET.
# Overnight windows wrap (start > end).
FX_SESSIONS = [
    {"id": "asia", "name": "Asia", "slang": "Tokyo tape", "start": "19:00", "end": "04:00", "plain": "Yen and overnight risk. USD/JPY usually liveliest here."},
    {"id": "london", "name": "London", "slang": "London open", "start": "03:00", "end": "12:00", "plain": "Primary FX liquidity. EUR/USD does most of its daily range here."},
    {"id": "london_focus", "name": "London focus", "slang": "London 9a-2p", "start": "09:00", "end": "14:00", "plain": "Your working London window. Overlap into New York."},
    {"id": "ny", "name": "New York", "slang": "NY session", "start": "08:00", "end": "17:00", "plain": "US cash and data. Spreads usually tightest in the London-NY overlap."},
    {"id": "overlap", "name": "London / NY overlap", "slang": "The overlap", "start": "08:00", "end": "12:00", "plain": "Both desks open. Highest FX volume of the day."},
]

EQUITY_SESSIONS = [
    {"id": "premarket", "name": "Premarket", "slang": "Pre", "start": "04:00", "end": "09:30", "plain": "Thin stock tape before the cash open. Wider spreads."},
    {"id": "rth", "name": "Regular hours", "slang": "Cash open", "start": "09:30", "end": "16:00", "plain": "NYSE/Nasdaq auction to close. This is the stock session that matters."},
    {"id": "after", "name": "After hours", "slang": "AH", "start": "16:00", "end": "20:00", "plain": "Post-close prints. News can move names; liquidity is worse."},
]

FUTURES_SESSIONS = [
    {"id": "globex", "name": "Globex", "slang": "Almost 24h", "start": "18:00", "end": "17:00", "plain": "CME Sunday 6pm ET through Friday 5pm, daily halt 5-6pm."},
    {"id": "rth", "name": "US cash hours", "slang": "RTH", "start": "09:30", "end": "16:00", "plain": "When the stock cash market is open. Index micros are busiest here."},
]

CLOCKS = [
    {
        "id": "1m",
        "name": "1 minute",
        "role": "Tape",
        "plain": "Tape/chart only; no directional decision is made from one-minute noise.",
    },
    {
        "id": "15m",
        "name": "15 minute",
        "role": "Intraday trigger",
        "plain": "Continuation trigger for FX, index micros, and shares.",
    },
    {
        "id": "1h",
        "name": "1 hour",
        "role": "Context / swing trigger",
        "plain": "Tactical context and the trigger clock for swing-first markets.",
    },
    {
        "id": "4h",
        "name": "4 hour",
        "role": "Grain",
        "plain": "Intermediate trend. Aether trades with it, not against it.",
    },
    {
        "id": "1d",
        "name": "Daily",
        "role": "Structural bias",
        "plain": "Daily structure governs every book; BTC/ETH use daily candles exclusively.",
    },
]


def _now() -> datetime:
    return datetime.now(ET)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _active(start: str, end: str, now: datetime) -> bool:
    cur = now.hour * 60 + now.minute
    a, b = _minutes(start), _minutes(end)
    if a == b:
        return True
    if a < b:
        return a <= cur < b
    return cur >= a or cur < b


def _kind(asset_id: str) -> str:
    aid = str(asset_id).lower()
    row = BY_ID.get(aid) or {}
    broker = str(row.get("broker") or "")
    if aid in {"btc", "eth"} or broker == "kraken":
        return "crypto"
    if broker == "tastyfx" or aid in {"eurusd", "usdjpy"}:
        return "fx"
    if broker == "ninjatrader":
        return "futures"
    return "equity"


def _decorate(rows: list[dict[str, str]], now: datetime) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        on = _active(row["start"], row["end"], now)
        out.append(
            {
                **row,
                "window": f"{row['start']}\u2013{row['end']} ET",
                "active": on,
                "state": "ACTIVE" if on else "closed",
            }
        )
    return out


def for_asset(asset_id: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    kind = _kind(asset_id)
    if kind == "crypto":
        sessions = [
            {
                "id": "always",
                "name": "Crypto",
                "slang": "24/7",
                "start": "00:00",
                "end": "00:00",
                "plain": "Spot crypto does not have a cash session. The tape is always open.",
                "window": "24/7",
                "active": True,
                "state": "ACTIVE",
            }
        ]
        applies = False
    elif kind == "fx":
        sessions = _decorate(FX_SESSIONS, now)
        applies = True
    elif kind == "futures":
        sessions = _decorate(FUTURES_SESSIONS, now)
        applies = True
    else:
        sessions = _decorate(EQUITY_SESSIONS, now)
        applies = True
    live = [s for s in sessions if s["active"]]
    profile = playbook_profile(asset_id)
    return {
        "asset_id": str(asset_id).lower(),
        "kind": kind,
        "timezone": "America/New_York",
        "clock": now.strftime("%a %H:%M ET"),
        "session_applies": applies,
        "always_open": kind == "crypto",
        "active": [s["name"] for s in live],
        "active_slang": [s["slang"] for s in live],
        "sessions": sessions,
        "timeframes": profile["clocks"],
        "playbook": {
            "primary": profile["primary"],
            "secondary": profile.get("secondary"),
            "cluster": profile["cluster"],
        },
        "same_as_bot": True,
    }


def desk_board(now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    books = []
    for aid in BY_ID:
        pack = for_asset(aid, now)
        books.append(
            {
                "id": aid,
                "symbol": BY_ID[aid]["symbol"],
                "kind": pack["kind"],
                "active": pack["active"],
                "always_open": pack["always_open"],
            }
        )
    fx = _decorate(FX_SESSIONS, now)
    eq = _decorate(EQUITY_SESSIONS, now)
    fut = _decorate(FUTURES_SESSIONS, now)
    return {
        "timezone": "America/New_York",
        "clock": now.strftime("%a %H:%M ET"),
        "fx": fx,
        "equity": eq,
        "futures": fut,
        "crypto": {"always_open": True, "note": "BTC and ETH do not use cash sessions."},
        "timeframes": CLOCKS,
        "books": books,
        "same_as_bot": True,
    }
