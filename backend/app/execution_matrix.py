"""AETHER-LOAD-002 execution capability matrix.

The matrix is an explicit paper-experiment contract. Unsupported product
capabilities are N/A rather than fabricated, and live execution is not
authorized here.
"""
from __future__ import annotations

from typing import Any

from app.instruments import supports_side
from app.universe import ASSETS

MATRIX_HORIZONS: tuple[str, ...] = ("scalp", "intraday", "swing")
MATRIX_SIDES: tuple[str, ...] = ("long", "short")

VALIDATION_REFERENCE_PRICES: dict[str, float] = {
    "eurusd": 1.10,
    "usdjpy": 150.0,
    "mes": 6000.0,
    "mnq": 21000.0,
    "mgc": 3000.0,
    "mcl": 70.0,
    "us10y": 110.0,
    "nvda": 180.0,
    "tsla": 450.0,
    "pltr": 180.0,
    "btc": 100000.0,
    "eth": 4000.0,
}

# Deliberately explicit: each book only gets horizons appropriate to its
# current product/playbook architecture.
ASSET_HORIZONS: dict[str, tuple[str, ...]] = {
    "eurusd": ("scalp", "intraday", "swing"),
    "usdjpy": ("scalp", "intraday", "swing"),
    "mes": ("scalp", "intraday", "swing"),
    "mnq": ("scalp", "intraday", "swing"),
    "mgc": ("intraday", "swing"),
    "mcl": ("intraday", "swing"),
    "us10y": ("swing",),
    "nvda": ("scalp", "intraday", "swing"),
    "tsla": ("scalp", "intraday", "swing"),
    "pltr": ("scalp", "intraday", "swing"),
    "btc": ("swing",),
    "eth": ("swing",),
}


def supported_horizons(asset_id: str) -> tuple[str, ...]:
    return ASSET_HORIZONS[str(asset_id).lower()]


def execution_mode(asset_id: str, horizon: str) -> str:
    aid = str(asset_id).lower()
    mode = str(horizon).lower()
    if aid in {"btc", "eth"} and mode == "swing":
        return "daily_swing"
    return mode


def clock_horizon(asset_id: str, horizon: str) -> str:
    aid = str(asset_id).lower()
    mode = str(horizon).lower()
    # Crypto spot stays on its completed-daily strategy clock.
    if aid in {"btc", "eth"} and mode == "swing":
        return "position"
    return mode


def matrix_cell_id(asset_id: str, horizon: str, side: str) -> str:
    return f"{str(asset_id).lower()}:{str(horizon).lower()}:{str(side).lower()}"


def validation_reference_price(
    asset_id: str,
    current_mark: float | None,
) -> tuple[float, str]:
    mark = float(current_mark or 0.0)
    if mark > 0:
        return mark, "current_paper_mark"
    aid = str(asset_id).lower()
    return float(VALIDATION_REFERENCE_PRICES[aid]), "synthetic_validation_reference"


def capability_cells() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    asset_ids = [str(row["id"]) for row in ASSETS]
    for aid in asset_ids:
        configured = set(supported_horizons(aid))
        for horizon in MATRIX_HORIZONS:
            for side in MATRIX_SIDES:
                horizon_ok = horizon in configured
                side_ok = supports_side(aid, side)
                supported = horizon_ok and side_ok
                reason = None
                if not horizon_ok:
                    reason = "horizon_not_configured_for_asset"
                elif not side_ok:
                    reason = "side_not_supported_by_product"
                rows.append(
                    {
                        "cell_id": matrix_cell_id(aid, horizon, side),
                        "asset_id": aid,
                        "horizon": horizon,
                        "side": side,
                        "execution_mode": execution_mode(aid, horizon),
                        "clock_horizon": clock_horizon(aid, horizon),
                        "supported": supported,
                        "status": "pending" if supported else "n/a",
                        "reason": reason,
                    }
                )
    return rows


def directional_summary() -> dict[str, Any]:
    asset_ids = [str(row["id"]) for row in ASSETS]
    long_assets = [aid for aid in asset_ids if supports_side(aid, "long")]
    short_assets = [aid for aid in asset_ids if supports_side(aid, "short")]
    return {
        "long_supported_assets": long_assets,
        "short_supported_assets": short_assets,
        "long_supported_count": len(long_assets),
        "short_supported_count": len(short_assets),
    }


def forced_execution_snapshot(
    asset_id: str,
    horizon: str,
    side: str,
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aid = str(asset_id).lower()
    mode = str(horizon).lower()
    direction = str(side).lower()
    if mode not in supported_horizons(aid):
        raise ValueError("horizon_not_configured_for_asset")
    if not supports_side(aid, direction):
        raise ValueError("side_not_supported_by_product")

    normal = dict(baseline or {})
    executable = "short" if direction == "short" else "buy"
    cell_id = matrix_cell_id(aid, mode, direction)
    entry_clock = "1m" if mode == "scalp" else "15m" if mode == "intraday" else "1h"
    if aid in {"btc", "eth"}:
        entry_clock = "1d"

    return {
        **normal,
        "signal": executable,
        "executable_signal": executable,
        "mode": execution_mode(aid, mode),
        "reason": "execution_matrix_override",
        "execution_status": "execution_test_forced",
        "signal_key": f"execution-matrix:{cell_id}",
        "risk_stop_pct": 10.0,
        "entry_clock": entry_clock,
        "bias_clock": "bypassed",
        "execution_test": True,
        "matrix_cell_id": cell_id,
        "matrix_horizon": mode,
        "matrix_side": direction,
        "would_have_blocked_by": normal.get("reason"),
        "normal_execution_status": normal.get("execution_status"),
        "normal_signal": normal.get("executable_signal"),
        "normal_quality_score": normal.get("quality_score"),
    }
