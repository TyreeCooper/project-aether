from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.engine import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    engine.start_loop()
    yield


app = FastAPI(title="Project Aether API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
        "venue": "paper-coingecko",
        "symbol": "BTC/USD",
        "postgres": "not_required_paper",
        "redis": "not_required_paper",
        "venue_ws": "public_rest_poll",
        "last_tick_age_ms": snap["last_tick_age_ms"],
        "live_keys_present": False,
        "paper_mode": True,
    }


@app.get("/api/v1/bot")
async def bot():
    return engine.snapshot()


@app.get("/api/v1/account")
async def account():
    snap = engine.snapshot()
    return {
        "usd_free": snap["usd"],
        "usd_total": snap["usd"],
        "btc_free": snap["btc"],
        "btc_total": snap["btc"],
        "equity_usd": snap["equity"],
        "realized_pnl_24h": snap["daily_realized"],
        "open_pnl": snap["open_pnl"],
        "margin_utilized_pct": 0.0,
        "mark_source": snap["mark_source"],
        "mark": snap["mark"],
    }


@app.get("/api/v1/audit")
async def audit():
    return {"events": list(engine.audit)}


@app.post("/api/v1/bot/start")
async def bot_start():
    return await engine.start_bot()


@app.post("/api/v1/bot/stop")
async def bot_stop():
    return await engine.stop_bot()


@app.post("/api/v1/orders/market")
async def market(side: str, body: QtyBody | None = None):
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}
    qty = body.qty if body else None
    return await engine.manual(side, qty)


@app.post("/api/v1/orders/flatten")
async def flatten():
    return await engine.flatten()


@app.post("/api/v1/risk/unlock")
async def unlock():
    return await engine.unlock()
