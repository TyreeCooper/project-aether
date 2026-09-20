from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(title="Project Aether API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_STATE = "OFFLINE"


@app.get("/api/v1/health")
async def health():
    return {
        "ok": True,
        "env": settings.aether_env,
        "venue": settings.venue,
        "symbol": settings.symbol,
        "postgres": "not_checked_phase0",
        "redis": "not_checked_phase0",
        "venue_ws": "disconnected",
        "last_tick_age_ms": None,
        "ts": datetime.now(timezone.utc).isoformat(),
        "live_keys_present": bool(settings.exchange_api_key),
    }


@app.get("/api/v1/bot")
async def bot():
    return {
        "state": BOT_STATE,
        "strategy": "sma_crossover",
        "flatten_lock": False,
        "paper_mode": settings.aether_env != "live",
        "reason": "Phase 0 stub — bot is not armed on process start (fail closed).",
    }


@app.get("/api/v1/account")
async def account():
    return {
        "usd_free": 0.0,
        "usd_total": 0.0,
        "btc_free": 0.0,
        "btc_total": 0.0,
        "equity_usd": 0.0,
        "realized_pnl_24h": 0.0,
        "open_pnl": 0.0,
        "margin_utilized_pct": 0.0,
        "mark_source": "unavailable",
    }
