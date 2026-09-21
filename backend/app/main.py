from contextlib import asynccontextmanager
from pathlib import Path
import hmac
import logging
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import learn, live, venue
from app.db import db_store
from app.desk import desk
from app.engine import engine
from app.paper_exec import install as install_harsh_paper
from app.universe import public_catalog

STATIC = Path(__file__).parent / "static"
ICON_LINKS = (
    '<link rel="icon" href="/favicon.svg?v=3" type="image/svg+xml"/>'
    '<link rel="icon" href="/static/aether-mark.svg?v=3" type="image/svg+xml"/>'
    '<link rel="apple-touch-icon" href="/static/apple-touch-icon.svg?v=3"/>'
    '<link rel="manifest" href="/static/site.webmanifest?v=3"/>'
    '<link rel="stylesheet" href="/static/desk.css"/>'
)

logger = logging.getLogger("aether.telemetry")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
logger.propagate = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("event=app_start phase=begin version=2.1.0")
    await engine.initialize_persistence()
    install_harsh_paper(engine)
    engine.start_loop()
    logger.info(
        "event=app_start phase=ready version=2.1.0 storage_configured=%s storage_initialized=%s live_ready=%s",
        db_store.status().get("configured"),
        db_store.status().get("initialized"),
        live.status().get("live_ready"),
    )
    try:
        yield
    finally:
        logger.info("event=app_shutdown phase=begin")
        await engine.shutdown()
        await db_store.close()
        logger.info("event=app_shutdown phase=complete")


app = FastAPI(title="Project Aether API", version="2.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_telemetry(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "event=http_request method=%s path=%s status=500 duration_ms=%.2f",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "event=http_request method=%s path=%s status=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


class AddAssetBody(BaseModel):
    kraken_pair: str = Field(min_length=2, max_length=40)


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
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/favicon.svg")
async def favicon_svg():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico")
async def favicon_ico():
    return FileResponse(STATIC / "aether-mark.svg", media_type="image/svg+xml")


@app.get("/api/v1/health")
async def health():
    snap = engine.snapshot()
    return {
        "ok": True,
        "env": "paper",
        "venue": snap.get("mark_source"),
        "watch": "binance.us",
        "symbols": [a["pair"] for a in public_catalog()],
        "universe": [a["symbol"] for a in public_catalog()],
        "last_tick_age_ms": snap["last_tick_age_ms"],
        "stale": snap.get("stale"),
        "paper_mode": True,
        "live_blocked": True,
        "live": live.status(),
        "storage": db_store.status(),
    }


@app.get("/api/v1/markets")
async def markets():
    try:
        items = await venue.fetch_markets()
    except Exception:
        items = public_catalog()
    return {"items": items, "paper_symbols": [a["pair"] for a in public_catalog()]}


@app.get("/api/v1/kraken/assets")
async def kraken_assets(
    q: str = Query(default="", max_length=40),
    limit: int = Query(default=40, ge=1, le=100),
):
    return {"items": await venue.discover_kraken_assets(search=q, limit=limit)}


@app.post("/api/v1/assets")
async def add_asset(
    body: AddAssetBody,
    _: None = Depends(require_operator),
):
    asset = await venue.resolve_kraken_asset(body.kraken_pair)
    if asset is None:
        raise HTTPException(status_code=404, detail="Kraken USD asset pair not found")
    return await desk.add_asset(asset)


@app.get("/api/v1/floor")
async def floor():
    return desk.floor_snapshot()


@app.get("/api/v1/assets/{asset_id}")
async def asset_page(asset_id: str):
    row = desk.asset_snapshot(asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown asset")
    return row


@app.get("/api/v1/desk/blotter")
async def desk_blotter(limit: int = Query(default=200, ge=1, le=500)):
    return {"items": desk.blotter(limit)}


@app.post("/api/v1/desk/arm")
async def desk_arm(_: None = Depends(require_operator)):
    return {"ok": True, **desk.arm()}


@app.post("/api/v1/desk/disarm")
async def desk_disarm(_: None = Depends(require_operator)):
    return {"ok": True, **desk.disarm()}


@app.get("/api/v1/live")
async def live_status():
    return live.status()


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


@app.get("/api/v1/learn")
async def learn_status():
    state = learn.load_learn()
    fills = await db_store.history_fills(500)
    state["live_exits"] = learn.score_exits(fills)
    state["bars_used"] = len(engine.bars_1m)
    champ = state.get("champion") or learn.CHAMPION
    state["champion"] = champ
    return state


@app.post("/api/v1/learn/review")
async def learn_review(_: None = Depends(require_operator)):
    fills = await db_store.history_fills(500)
    return learn.review(list(engine.bars_1m), fills)


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
        "live": live.status(),
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
