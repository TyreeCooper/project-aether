"""One intel pack per asset. The page and the bot read the same object."""
from __future__ import annotations

from typing import Any


def _n(v: Any, digits: int = 4) -> float | None:
    try:
        if v is None:
            return None
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _field(key: str, slang: str, plain: str, value: Any, unit: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "label": slang,
        "means": plain,
        "value": value,
        "unit": unit,
    }


def _call_plain(
    signal: str | None,
    in_pos: bool,
    execution_status: str | None = None,
) -> tuple[str, str, str]:
    if in_pos:
        return (
            "IN POSITION",
            "Already long",
            "The book owns this asset. Its playbook manages the exit, not a new entry.",
        )
    if signal == "buy" and execution_status == "long_adapter_required":
        return (
            "LONG SETUP",
            "Grain is up",
            "The setup qualifies, but this instrument still needs its broker-specific "
            "paper execution adapter. Aether will not fabricate a fill.",
        )
    if signal == "buy":
        return (
            "BUY",
            "Green light",
            "The same rule the bot uses says this tape qualifies for a paper buy.",
        )
    if signal == "sell":
        return "FLAT / EXIT", "Get out", "The rule wants this book flat."
    if signal == "short":
        return (
            "SHORT SETUP",
            "Grain is down",
            "A bearish setup qualifies, but the current paper wallet is long-only. "
            "Aether exposes it without fabricating short execution.",
        )
    return (
        "NO TRADE",
        "Stand down",
        "No mode currently qualifies. Aether does not force activity just to stay invested.",
    )


def build_intel(
    *,
    view: dict[str, Any],
    strategy: dict[str, Any],
    analytics: dict[str, Any],
    capture: dict[str, Any] | None = None,
    window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qty = float(view.get("qty") or 0)
    in_pos = qty > 0
    signal = strategy.get("signal")
    execution_status = str(strategy.get("execution_status") or "")
    call, slang, plain = _call_plain(
        str(signal) if signal else None,
        in_pos,
        execution_status,
    )
    mark = _n(view.get("mark"), 8)
    bid = _n(view.get("bid"), 8)
    ask = _n(view.get("ask"), 8)
    watch = _n(view.get("watch_last"), 8)
    spread = None
    spread_bps = None
    if bid and ask and bid > 0:
        spread = round(ask - bid, 8)
        spread_bps = round((ask - bid) / bid * 10_000, 2)
    basis = None
    if watch is not None and mark is not None:
        basis = round(watch - mark, 8)
    reason = str(strategy.get("reason") or view.get("reason") or "warming")
    profile = strategy.get("playbook") or view.get("playbook") or {}
    cards = [
        {
            "id": "call",
            "title": "The call",
            "slang": slang,
            "plain": plain,
            "tone": "good" if call == "BUY" else ("warn" if in_pos else "flat"),
            "headline": call,
            "fields": [
                _field("signal", "Signal", "Bot decision on this book", call),
                _field("reason", "Why / reason code", "Internal rule name the engine logged", reason),
                _field("quality", "Setup quality", "How clean the breakout/trend look is", strategy.get("quality_score")),
                _field("hurdle", "Cost hurdle", "Move needed just to cover fees + slip", strategy.get("hurdle_pct"), "%"),
            ],
        },
        {
            "id": "playbook",
            "title": "Playbook",
            "slang": "Trade with the grain",
            "plain": (
                "Asset-specific mode, higher-timeframe bias, trigger clock, "
                "and execution capability."
            ),
            "tone": "struct",
            "headline": strategy.get("mode") or profile.get("primary"),
            "fields": [
                _field(
                    "primary",
                    "Primary mode",
                    "First strategy Aether checks for this asset",
                    profile.get("primary"),
                ),
                _field(
                    "secondary",
                    "Secondary mode",
                    "Fallback opportunity channel when primary has no setup",
                    profile.get("secondary"),
                ),
                _field(
                    "direction",
                    "Dominant direction",
                    "Direction implied by aligned higher-timeframe structure",
                    strategy.get("direction"),
                ),
                _field(
                    "daily",
                    "Daily grain",
                    "Structural daily direction",
                    strategy.get("daily_grain"),
                ),
                _field(
                    "four_hour",
                    "4H grain",
                    "Intermediate trend direction",
                    strategy.get("four_hour_grain"),
                ),
                _field(
                    "one_hour",
                    "1H context",
                    "Tactical direction used by intraday playbooks",
                    strategy.get("one_hour_grain"),
                ),
                _field(
                    "entry_clock",
                    "Entry clock",
                    "Completed candle timeframe allowed to trigger entry",
                    strategy.get("entry_clock"),
                ),
                _field(
                    "execution",
                    "Execution state",
                    "Short setups stay observation-only until broker short adapters exist",
                    strategy.get("execution_status"),
                ),
            ],
        },
        {
            "id": "tape",
            "title": "The tape",
            "slang": "Bid / ask / last",
            "plain": (
                "Live/public venue prices for this book. Bid is what you can sell to, "
                "ask is what you pay, and last is the latest mark."
            ),
            "tone": "tape",
            "headline": mark,
            "fields": [
                _field("mark", "Last / mark", "Most recent Kraken trade used as the book price", mark, "USD"),
                _field("bid", "Bid", "Best price a buyer will pay right now", bid, "USD"),
                _field("ask", "Ask", "Best price a seller will take right now", ask, "USD"),
                _field("spread", "Spread", "Gap between ask and bid. Wider = more expensive to trade", spread, "USD"),
                _field("spread_bps", "Spread in bps", "That same gap in basis points (1 bp = 0.01%)", spread_bps, "bps"),
                _field("watch", "Watch last (Binance.US)", "Same coin on the watch venue, not used for fills", watch, "USD"),
                _field("basis", "Basis", "Watch last minus Kraken last. Large basis = venues disagree", basis, "USD"),
            ],
        },
        {
            "id": "structure",
            "title": "Market structure",
            "slang": "Range / change",
            "plain": "Where price sits versus the recent 1-minute window the bot actually sees.",
            "tone": "struct",
            "headline": analytics.get("change_pct"),
            "fields": [
                _field("change", "Window change", "Percent move from first bar in this window to last", analytics.get("change_pct"), "%"),
                _field("high", "Window high", "Highest 1m high in the chart window", (window or {}).get("high"), "USD"),
                _field("low", "Window low", "Lowest 1m low in the chart window", (window or {}).get("low"), "USD"),
                _field("bars", "Bars the bot sees", "How many 1-minute candles are in this book", (window or {}).get("bars") or view.get("bars")),
                _field(
                    "venue",
                    "Execution venue",
                    "Broker/venue assigned to this official book",
                    view.get("broker") or view.get("kraken"),
                ),
            ],
        },
        {
            "id": "book",
            "title": "This book",
            "slang": "Inventory",
            "plain": "What this paper account owns in this coin, and the stop protecting it.",
            "tone": "good" if in_pos else "flat",
            "headline": "LONG" if in_pos else "FLAT",
            "fields": [
                _field("qty", "Size / qty", "How many coins this book holds", _n(qty, 8), view.get("symbol")),
                _field("avg", "Avg entry", "Average fill price of the open pile", _n(view.get("avg"), 8), "USD"),
                _field("value", "Position value", "Qty times mark, in dollars", _n(view.get("position_value"), 4), "USD"),
                _field("open_pnl", "Open P&L", "Unrealized profit or loss if flattened at mark", _n(view.get("open_pnl"), 4), "USD"),
                _field("stop", "Hard stop", "Price that forces a sell. Frozen at entry, only ratchets up", _n(view.get("stop"), 8), "USD"),
            ],
        },
        {
            "id": "score",
            "title": "Scorecard",
            "slang": "Track record",
            "plain": "Closed paper trades on this coin only. Not the whole desk.",
            "tone": "score",
            "headline": analytics.get("realized_pnl"),
            "fields": [
                _field("realized", "Realized P&L", "Locked-in profit after sells, fees included", analytics.get("realized_pnl"), "USD"),
                _field("trades", "Closed trades", "Number of completed round-trips", analytics.get("trades")),
                _field("wl", "W / L", "Wins versus losses on this book", f"{analytics.get('wins', 0)} / {analytics.get('losses', 0)}"),
                _field("win", "Win rate", "Share of closed trades that made money", analytics.get("win_rate_pct"), "%"),
                _field("pf", "Profit factor", "Gross wins divided by gross losses. Under 1.0 = net loser", analytics.get("profit_factor")),
                _field("fees", "Fees paid", "Kraken-style taker fees charged on this book", analytics.get("fees"), "USD"),
            ],
        },
    ]
    cap = capture or {}
    if cap.get("state") in {"open", "last_closed"}:
        cards.append(
            {
                "id": "excursion",
                "title": "Trade quality",
                "slang": "MFE / MAE",
                "plain": "MFE is the best the trade got. MAE is the worst dip. Capture is how much of the good move you kept after fees.",
                "tone": "exc",
                "headline": cap.get("net_return_pct") if cap.get("state") == "last_closed" else cap.get("mfe_pct"),
                "fields": [
                    _field("mfe", "MFE", "Max favorable excursion — best % the trade reached", cap.get("mfe_pct"), "%"),
                    _field("mae", "MAE", "Max adverse excursion — worst % dip while in the trade", cap.get("mae_pct"), "%"),
                    _field("net", "Net return", "What you actually kept after fees and slip", cap.get("net_return_pct"), "%"),
                    _field("capture", "Capture", "Net return as a share of MFE", cap.get("capture_efficiency_pct"), "%"),
                    _field("miss", "Left on the table", "MFE minus what was realized", cap.get("net_missed_opportunity_pct"), "%"),
                ],
            }
        )
    return {
        "pair": view.get("pair"),
        "asset_id": view.get("id"),
        "same_as_bot": True,
        "call": call,
        "signal": signal,
        "reason": reason,
        "in_position": in_pos,
        "cards": cards,
    }
