"""Safe Top-100 discovery handoff into Scout intake and the deep trading runtime.

Every focused instrument advances to Scout intake. Instruments already commissioned
for the autonomous deep runtime are SCOUT_READY; the rest are SCOUT_QUEUED while
their product/playbook/execution requirements are completed. Provider ranking is an
attention priority, never an execution veto for an otherwise commissioned strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_SEED_SYMBOL_MAP = {
    ("Kraken", "BTC/USD"): "btc",
    ("Kraken", "ETH/USD"): "eth",
    ("tastyfx", "C:EURUSD"): "eurusd",
    ("tastyfx", "EURUSD"): "eurusd",
    ("tastyfx", "EUR/USD"): "eurusd",
    ("tastyfx", "C:USDJPY"): "usdjpy",
    ("tastyfx", "USDJPY"): "usdjpy",
    ("tastyfx", "USD/JPY"): "usdjpy",
    ("IBKR", "NVDA"): "nvda",
    ("IBKR", "TSLA"): "tsla",
    ("IBKR", "PLTR"): "pltr",
}
_NINJA_PRODUCT_MAP = {
    "MES": "mes",
    "MNQ": "mnq",
    "MGC": "mgc",
    "MCL": "mcl",
    "ZN": "us10y",
}
_AUTONOMOUS_DEEP_ASSETS = frozenset({"btc", "eth"})


@dataclass(frozen=True, slots=True)
class FocusHandoff:
    provider: str
    symbol: str
    focus_key: str
    provider_rank: int
    canonical_asset_id: str | None
    state: str
    blockers: tuple[str, ...]


def canonical_seed_asset(
    *,
    provider: str,
    symbol: str,
    product_code: str | None = None,
) -> str | None:
    p = str(provider).strip()
    s = str(symbol).strip().upper()
    if p == "NinjaTrader":
        code = str(product_code or "").strip().upper()
        return _NINJA_PRODUCT_MAP.get(code)
    return _SEED_SYMBOL_MAP.get((p, s))


def focus_handoff_rows(
    focus_pool: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
) -> tuple[FocusHandoff, ...]:
    out: list[FocusHandoff] = []
    for row in focus_pool:
        provider = str(row.get("provider") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        focus_key = str(row.get("focus_key") or "").strip()
        rank = int(row.get("rank") or 0)
        canonical = canonical_seed_asset(
            provider=provider,
            symbol=symbol,
            product_code=(
                None
                if row.get("product_code") is None
                else str(row.get("product_code"))
            ),
        )

        blockers: list[str] = []
        if canonical is None:
            blockers.append("dynamic_product_registry_binding_required")
            if provider == "Kraken":
                blockers.append("dynamic_crypto_playbook_binding_required")
            elif provider == "IBKR":
                blockers.append("dynamic_equity_playbook_binding_required")
            elif provider == "tastyfx":
                blockers.append("dynamic_fx_playbook_binding_required")
            elif provider == "NinjaTrader":
                blockers.append("dynamic_futures_product_economics_required")
        elif canonical not in _AUTONOMOUS_DEEP_ASSETS:
            blockers.append("strategy_supervisor_not_commissioned_for_asset")
            if provider != "Kraken":
                blockers.append("execution_provider_binding_pending")

        state = "SCOUT_READY" if not blockers else "SCOUT_QUEUED"
        out.append(
            FocusHandoff(
                provider=provider,
                symbol=symbol,
                focus_key=focus_key,
                provider_rank=rank,
                canonical_asset_id=canonical,
                state=state,
                blockers=tuple(blockers),
            )
        )
    return tuple(out)


def handoff_payload(rows: tuple[FocusHandoff, ...]) -> list[dict[str, object]]:
    return [
        {
            "provider": row.provider,
            "symbol": row.symbol,
            "focus_key": row.focus_key,
            "provider_rank": row.provider_rank,
            "canonical_asset_id": row.canonical_asset_id,
            "state": row.state,
            "blockers": list(row.blockers),
        }
        for row in rows
    ]
