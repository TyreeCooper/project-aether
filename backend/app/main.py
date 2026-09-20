import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.engine import engine
from app.security import AuthContext, require_operator, require_step_up
from app.config import settings
from app.venue import KrakenSpotReadOnlyClient


@asynccontextmanager
async def lifespan(_: FastAPI):
    engine.start_loop()
    yield

    close = getattr(engine.market_data, "close", None)
    if close is not None:
        await close()


app = FastAPI(title="Project Aether API", version="0.3.0", lifespan=lifespan)

_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
frontend_origin = os.getenv("FRONTEND_ORIGIN")
if frontend_origin:
    _origins.append(frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QtyBody(BaseModel):
    qty: float | None = Field(default=None, gt=0, le=1)


@app.get("/api/v1/health")
async def health():
    snap = engine.snapshot()
    return {
        "ok": True,
        "env": "paper",
        "venue": "paper-public-market-data",
        "symbol": "BTC/USD",
        "postgres": "not_required_paper",
        "redis": "not_required_paper",
        "venue_ws": snap["mark_source"],
        "last_tick_age_ms": snap["last_tick_age_ms"],
        "live_keys_present": False,
        "paper_mode": True,
    }


@app.get("/api/v1/status")
async def status(_auth: AuthContext = Depends(require_operator)):
    snap = engine.snapshot()
    return {
        "state": snap["state"],
        "paper_mode": snap["paper_mode"],
        "live_blocked": snap["live_blocked"],
        "flatten_lock": snap["flatten_lock"],
        "symbol": "BTC/USD",
        "mark": snap["mark"],
        "mark_source": snap["mark_source"],
        "last_tick_age_ms": snap["last_tick_age_ms"],
        "persistence_enabled": snap["persistence_enabled"],
        "persistence_healthy": snap["persistence_healthy"],
        "profitability_enforced": snap["profitability_enforced"],
        "last_profitability_reason": snap["last_profitability_reason"],
    }


@app.get("/api/v1/bot")
async def bot(_auth: AuthContext = Depends(require_operator)):
    return engine.snapshot()


@app.get("/api/v1/account")
async def account(_auth: AuthContext = Depends(require_operator)):
    snap = engine.snapshot()
    return {
        "usd_free": snap["usd"],
        "usd_total": snap["usd"],
        "btc_free": snap["btc"],
        "btc_total": snap["btc"],
        "equity_usd": snap["equity"],
        "realized_pnl_24h": snap["daily_realized"],
        "realized_pnl_session": snap["realized_session"],
        "gross_realized_pnl": snap["gross_realized"],
        "open_pnl": snap["open_pnl"],
        "total_fees": snap["total_fees"],
        "total_spread_cost": snap["total_spread_cost"],
        "total_slippage_cost": snap["total_slippage_cost"],
        "margin_utilized_pct": 0.0,
        "mark_source": snap["mark_source"],
        "mark": snap["mark"],
    }


@app.get("/api/v1/positions")
async def positions(_auth: AuthContext = Depends(require_operator)):
    snap = engine.snapshot()
    return {
        "positions": [
            {
                "symbol": "BTC/USD",
                "qty_open": snap["btc"],
                "avg_entry": snap["avg_entry"],
                "mark": snap["mark"],
                "open_pnl": snap["open_pnl"],
                "state": snap["state"],
            }
        ]
    }


@app.get("/api/v1/orders")
async def orders(_auth: AuthContext = Depends(require_operator)):
    return {"orders": list(engine.orders)}


@app.get("/api/v1/trades")
async def trades(_auth: AuthContext = Depends(require_operator)):
    return {"trades": list(engine.fills)}


@app.get("/api/v1/performance")
async def performance(_auth: AuthContext = Depends(require_operator)):
    snap = engine.snapshot()
    return {
        "equity_usd": snap["equity"],
        "gross_realized_pnl": snap["gross_realized"],
        "net_realized_pnl": snap["realized_session"],
        "open_pnl": snap["open_pnl"],
        "daily_realized_pnl": snap["daily_realized"],
        "total_fees": snap["total_fees"],
        "total_spread_cost": snap["total_spread_cost"],
        "total_slippage_cost": snap["total_slippage_cost"],
        "peak_equity": snap["peak_equity"],
        "max_drawdown_pct": snap["max_drawdown_pct"],
        "closed_trade_count": snap["closed_trade_count"],
        "winning_trades": snap["winning_trades"],
        "losing_trades": snap["losing_trades"],
        "win_rate_pct": snap["win_rate_pct"],
        "avg_winner": snap["avg_winner"],
        "avg_loser": snap["avg_loser"],
    }


@app.get("/api/v1/audit")
async def audit(_auth: AuthContext = Depends(require_operator)):
    return {"events": list(engine.audit)}


@app.post("/api/v1/bot/start")
async def bot_start(_auth: AuthContext = Depends(require_step_up)):
    return await engine.start_bot()


@app.post("/api/v1/bot/stop")
async def bot_stop(_auth: AuthContext = Depends(require_operator)):
    return await engine.stop_bot()


@app.post("/api/v1/orders/market")
async def market(side: str, body: QtyBody | None = None, _auth: AuthContext = Depends(require_step_up)):
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}
    qty = body.qty if body else None
    return await engine.manual(side, qty)


@app.post("/api/v1/orders/flatten")
async def flatten(_auth: AuthContext = Depends(require_operator)):
    return await engine.flatten()


@app.post("/api/v1/risk/unlock")
async def unlock(_auth: AuthContext = Depends(require_step_up)):
    return await engine.unlock()


@app.post("/api/v1/risk/reset-fault")
async def reset_fault(_auth: AuthContext = Depends(require_step_up)):
    return await engine.reset_fault()


@app.get("/api/v1/venue/kraken/readiness")
async def kraken_readiness(_auth: AuthContext = Depends(require_operator)):
    if not settings.kraken_read_api_key or not settings.kraken_read_api_secret:
        return {
            "configured": False,
            "ready": False,
            "reason": "read_only_credentials_not_configured",
        }

    client = KrakenSpotReadOnlyClient(
        api_key=settings.kraken_read_api_key,
        api_secret=settings.kraken_read_api_secret,
    )

    try:
        key_info = await client.get_api_key_info()
        permissions = key_info.get("permissions") or []
        assessment = client.assess_permissions(permissions)

        response: dict[str, object] = {
            "configured": True,
            "ready": assessment.valid_for_read_only_reconciliation,
            "missing_permissions": list(assessment.missing_permissions),
            "prohibited_permissions": list(assessment.prohibited_permissions),
            "ip_allowlist_configured": bool(key_info.get("ipAllowlist")),
        }

        if assessment.valid_for_read_only_reconciliation:
            balances = await client.get_balances()
            response["btc_balance"] = client.extract_btc_balance(balances)

        return response
    except Exception:
        return {
            "configured": True,
            "ready": False,
            "reason": "kraken_readiness_check_failed",
        }


@app.post("/api/v1/venue/kraken/reconcile")
async def kraken_reconcile(_auth: AuthContext = Depends(require_operator)):
    if not settings.kraken_read_api_key or not settings.kraken_read_api_secret:
        return {
            "ok": False,
            "error": "read_only_credentials_not_configured",
        }

    client = KrakenSpotReadOnlyClient(
        api_key=settings.kraken_read_api_key,
        api_secret=settings.kraken_read_api_secret,
    )

    try:
        key_info = await client.get_api_key_info()
        assessment = client.assess_permissions(key_info.get("permissions") or [])
        if not assessment.valid_for_read_only_reconciliation:
            return {
                "ok": False,
                "error": "read_only_credentials_not_safe",
                "missing_permissions": list(assessment.missing_permissions),
                "prohibited_permissions": list(assessment.prohibited_permissions),
            }

        balances = await client.get_balances()
        venue_btc = client.extract_btc_balance(balances)
        return await engine.reconcile_position(
            venue_btc=venue_btc,
            source="kraken_spot_read_only",
        )
    except Exception:
        return {
            "ok": False,
            "error": "kraken_reconciliation_failed",
        }
