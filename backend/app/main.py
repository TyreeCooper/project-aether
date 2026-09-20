from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import venue
from app.db import db_store
from app.engine import engine

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await engine.initialize_persistence()
    engine.start_loop()
    try:
        yield
    finally:
        await engine.shutdown()
        await db_store.close()


app = FastAPI(title="Project Aether API", version="0.5.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QtyBody(BaseModel):
    qty: float | None = Field(default=None, gt=0, le=1)


def _basis(exec_last, watch_last):
    if exec_last is None or watch_last is None:
        return None
    return round(float(watch_last) - float(exec_last), 2)


@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/v1/health")
async def health():
    snap = engine.snapshot()
    return {
        "ok": True,
        "env": "paper",
        "venue": snap.get("mark_source"),
        "watch": "binance.us",
        "symbol": "BTC/USD",
        "last_tick_age_ms": snap["last_tick_age_ms"],
        "stale": snap.get("stale"),
        "paper_mode": True,
        "live_blocked": True,
        "storage": db_store.status(),
    }


@app.get("/api/v1/storage")
async def storage():
    return db_store.status()


@app.get("/api/v1/bot")
async def bot():
    return engine.snapshot()


@app.get("/api/v1/account")
async def account():
    snap = engine.snapshot()
    watch = None
    try:
        watch = await venue.fetch_binance_us()
    except Exception:
        watch = None
    watch_last = watch.get("last") if watch else None
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
        "bid": snap.get("bid"),
        "ask": snap.get("ask"),
        "stale": snap.get("stale"),
        "watch_source": watch.get("source") if watch else None,
        "watch_last": watch_last,
        "watch_bid": watch.get("bid") if watch else None,
        "watch_ask": watch.get("ask") if watch else None,
        "watch_basis_usd": _basis(snap.get("mark"), watch_last),
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
