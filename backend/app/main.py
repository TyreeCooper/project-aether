from contextlib import asynccontextmanager
from pathlib import Path
import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
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


app = FastAPI(title="Project Aether API", version="1.1.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QtyBody(BaseModel):
    qty: float | None = Field(default=None, gt=0, le=1)


class ConfigBody(BaseModel):
    short_ma: int = Field(ge=2, le=100)
    long_ma: int = Field(ge=3, le=200)
    stop_loss_pct: float = Field(ge=0.1, le=20)
    position_size_btc: float = Field(gt=0, le=1)
    max_position_btc: float = Field(gt=0, le=1)
    max_drawdown_pct: float = Field(ge=0.5, le=50)
    daily_loss_cap: float = Field(ge=1, le=10000)


OPERATOR_TOKEN = os.getenv("AETHER_OPERATOR_TOKEN", "").strip()


def require_operator(
    x_operator_token: str | None = Header(default=None),
) -> None:
    if not OPERATOR_TOKEN:
        return
    if not x_operator_token or not hmac.compare_digest(
        x_operator_token,
        OPERATOR_TOKEN,
    ):
        raise HTTPException(status_code=401, detail="operator authentication required")


def _basis(exec_last, watch_last):
    if exec_last is None or watch_last is None:
        return None
    return round(float(watch_last) - float(exec_last), 2)


@app.get("/")
async def home():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    if "ui-tune.css" not in html:
        html = html.replace(
            "</head>",
            '<link rel="stylesheet" href="/static/ui-tune.css"/></head>',
            1,
        )
    if "ledger-order.js" not in html:
        html = html.replace(
            "</body>",
            '<script src="/static/ledger-order.js"></script></body>',
            1,
        )
    return HTMLResponse(html)


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


@app.get("/api/v1/auth/status")
async def auth_status():
    return {
        "configured": bool(OPERATOR_TOKEN),
        "enforced_on_mutations": bool(OPERATOR_TOKEN),
    }


@app.post("/api/v1/auth/verify")
async def auth_verify(_: None = Depends(require_operator)):
    return {"ok": True, "authenticated": True}


@app.get("/api/v1/analytics")
async def analytics(limit: int = Query(default=5000, ge=1, le=5000)):
    return await db_store.analytics(limit)


@app.get("/api/v1/config")
async def config():
    snap = engine.snapshot()
    return {
        "short_ma": snap["short_ma"],
        "long_ma": snap["long_ma"],
        "stop_loss_pct": snap["stop_loss_pct"],
        "position_size_btc": snap["position_size_btc"],
        "max_position_btc": snap["max_position_btc"],
        "max_drawdown_pct": snap["max_drawdown_pct"],
        "daily_loss_cap": snap["daily_loss_cap"],
        "editable": snap["state"] == "OFFLINE" and snap["btc"] == 0,
    }


@app.post("/api/v1/config")
async def update_config(
    body: ConfigBody,
    _: None = Depends(require_operator),
):
    return await engine.update_config(body.model_dump())


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


@app.get("/api/v1/history/orders")
async def history_orders(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": await db_store.history_orders(limit), "limit": limit}


@app.get("/api/v1/history/fills")
async def history_fills(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": await db_store.history_fills(limit), "limit": limit}


@app.get("/api/v1/history/risk")
async def history_risk(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": await db_store.history_risk(limit), "limit": limit}


@app.get("/api/v1/history/account")
async def history_account(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": await db_store.history_account(limit), "limit": limit}


@app.get("/api/v1/history/positions")
async def history_positions(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": await db_store.history_positions(limit), "limit": limit}


@app.get("/api/v1/history/bot")
async def history_bot(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": await db_store.history_bot(limit), "limit": limit}


@app.post("/api/v1/bot/start")
async def bot_start(_: None = Depends(require_operator)):
    return await engine.start_bot()


@app.post("/api/v1/bot/stop")
async def bot_stop(_: None = Depends(require_operator)):
    return await engine.stop_bot()


@app.post("/api/v1/orders/market")
async def market(
    side: str,
    body: QtyBody | None = None,
    _: None = Depends(require_operator),
):
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}
    qty = body.qty if body else None
    return await engine.manual(side, qty)


@app.post("/api/v1/orders/flatten")
async def flatten(_: None = Depends(require_operator)):
    return await engine.flatten()


@app.post("/api/v1/risk/unlock")
async def unlock(_: None = Depends(require_operator)):
    return await engine.unlock()


app.mount("/static", StaticFiles(directory=STATIC), name="static")
