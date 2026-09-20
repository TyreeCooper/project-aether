"""In-process paper trading orchestrator.

Market data, execution, portfolio accounting, profitability, risk, and audit
are separate concerns. Live execution remains blocked.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.audit import AuditEvent, InMemoryAuditSink
from app.config import settings
from app.db.ledger import LedgerRepository
from app.execution import ExecutionGateway, ExecutionResult, OrderRequest, PaperExecutionGateway
from app.market_data import CoinGeckoMarketDataProvider, KrakenWebSocketMarketDataProvider, MarketDataProvider
from app.portfolio import PaperPortfolio
from app.profitability import ProfitabilityDecision, ProfitabilityGate, StaticCostModel
from app.risk import deny_entry
from app.services import EntryDecisionService
from app.state import BotState, transition
from app.strategy import crossover_signal, sma

STARTING_USD = 10_000.0
TAKER_FEE = 0.0026
PAPER_SPREAD_BPS = 0.0
PAPER_SLIPPAGE_BPS = 0.0
MIN_EDGE_MULTIPLE = 1.25
POLL_SECONDS = 15
SHORT_MA = 8
LONG_MA = 21
STOP_LOSS_PCT = 2.0
POSITION_BTC = 0.01
MAX_POSITION_BTC = 0.02
MAX_DRAWDOWN_PCT = 8.0
DAILY_LOSS_CAP = 250.0
MAX_CONSECUTIVE_MARK_FAILURES = 3
MAX_MARK_AGE_MS = 30_000
SYMBOL = "BTC/USD"


def _default_market_data_provider() -> MarketDataProvider:
    provider = settings.market_data_provider.strip().lower()
    if provider == "kraken_ws":
        return KrakenWebSocketMarketDataProvider()
    if provider == "coingecko":
        return CoinGeckoMarketDataProvider()
    raise ValueError(f"unsupported market_data_provider: {settings.market_data_provider}")


class PaperEngine:
    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        execution: ExecutionGateway | None = None,
        portfolio: PaperPortfolio | None = None,
        profitability_gate: ProfitabilityGate | None = None,
        audit_sink: InMemoryAuditSink | None = None,
        ledger: LedgerRepository | None = None,
    ) -> None:
        self.paper_mode = True
        self.live_blocked = True
        self.state = BotState.OFFLINE.value
        self.flatten_lock = False
        self.symbol = SYMBOL

        self.market_data = market_data or _default_market_data_provider()
        self.execution = execution or PaperExecutionGateway(
            taker_fee_rate=TAKER_FEE,
            spread_bps=PAPER_SPREAD_BPS,
            slippage_bps=PAPER_SLIPPAGE_BPS,
        )
        self.portfolio = portfolio or PaperPortfolio(starting_usd=STARTING_USD)
        self.profitability_gate = profitability_gate or ProfitabilityGate(
            StaticCostModel(
                taker_fee_rate=TAKER_FEE,
                spread_bps=PAPER_SPREAD_BPS,
                slippage_bps=PAPER_SLIPPAGE_BPS,
            ),
            minimum_edge_multiple=MIN_EDGE_MULTIPLE,
            enforce=False,
        )
        self.entry_decisions = EntryDecisionService(self.profitability_gate)
        self.last_profitability: ProfitabilityDecision | None = None
        self.audit_sink = audit_sink or InMemoryAuditSink(max_events=500)
        self.ledger = ledger if ledger is not None else (
            LedgerRepository() if settings.persistence_enabled else None
        )

        self.mark: float | None = None
        self.mark_source = "unavailable"
        self.last_tick_age_ms: int | None = None
        self._last_tick_mono: float | None = None
        self._consecutive_mark_failures = 0
        self.closes: deque[float] = deque(maxlen=300)
        self.orders: deque[dict[str, Any]] = deque(maxlen=500)
        self.fills: deque[dict[str, Any]] = deque(maxlen=500)

        self.short_ma = SHORT_MA
        self.long_ma = LONG_MA
        self.stop_loss_pct = STOP_LOSS_PCT
        self.position_size = POSITION_BTC
        self.max_position = MAX_POSITION_BTC

        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._log(
            "INFO",
            "Paper engine constructed. Bot OFFLINE. Live execution blocked.",
            component="engine",
            event="engine_constructed",
        )

    @property
    def audit(self):
        return self.audit_sink.events

    def _set_state(self, target: BotState | str) -> None:
        self.state = transition(self.state, target).value

    def _trip_market_data_kill_switch(self, reason: str) -> None:
        self.flatten_lock = True
        self._set_state(BotState.FAULT)
        self._log(
            "ERROR",
            f"Market-data kill switch tripped: {reason}",
            component="risk_guard",
            event="market_data_kill_switch",
            payload={
                "reason": reason,
                "consecutive_failures": self._consecutive_mark_failures,
            },
        )

    def _log(
        self,
        level: str,
        message: str,
        *,
        actor: str = "system",
        component: str = "engine",
        event: str = "message",
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        audit_event = AuditEvent.create(
            level=level,
            message=message,
            actor=actor,
            component=component,
            event=event,
            correlation_id=correlation_id,
            payload=payload,
        )
        self.audit_sink.emit(audit_event)

        if self.ledger is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self.ledger.record_audit(audit_event.to_dict()))

    @property
    def usd(self) -> float:
        return self.portfolio.usd

    @property
    def btc(self) -> float:
        return self.portfolio.btc

    @property
    def avg_entry(self) -> float:
        return self.portfolio.avg_entry

    @property
    def realized_session(self) -> float:
        return self.portfolio.realized_session

    @property
    def daily_realized(self) -> float:
        return self.portfolio.daily_realized

    @property
    def peak_equity(self) -> float:
        return self.portfolio.peak_equity

    @property
    def equity(self) -> float:
        return self.portfolio.equity(self.mark)

    @property
    def open_pnl(self) -> float:
        return self.portfolio.open_pnl(self.mark)

    def snapshot(self) -> dict[str, Any]:
        age = None
        if self._last_tick_mono is not None:
            age = int((time.monotonic() - self._last_tick_mono) * 1000)
            self.last_tick_age_ms = age

        short = sma(list(self.closes), self.short_ma)
        long = sma(list(self.closes), self.long_ma)
        p = self.portfolio.snapshot(self.mark)
        profitability = self.last_profitability

        return {
            "state": self.state,
            "paper_mode": self.paper_mode,
            "live_blocked": self.live_blocked,
            "flatten_lock": self.flatten_lock,
            "strategy": "sma_crossover",
            "short_ma": self.short_ma,
            "long_ma": self.long_ma,
            "stop_loss_pct": self.stop_loss_pct,
            "position_size_btc": self.position_size,
            "bars": len(self.closes),
            "warm_up_needed": self.long_ma + 1,
            "short_value": short,
            "long_value": long,
            "mark": self.mark,
            "mark_source": self.mark_source,
            "last_tick_age_ms": age,
            "consecutive_mark_failures": self._consecutive_mark_failures,
            "max_mark_age_ms": MAX_MARK_AGE_MS,
            "usd": p.usd,
            "btc": p.btc,
            "equity": p.equity,
            "avg_entry": p.avg_entry,
            "open_pnl": p.open_pnl,
            "realized_session": p.realized_session,
            "daily_realized": p.daily_realized,
            "gross_realized": p.gross_realized,
            "total_fees": p.total_fees,
            "total_spread_cost": p.total_spread_cost,
            "total_slippage_cost": p.total_slippage_cost,
            "peak_equity": p.peak_equity,
            "max_drawdown_pct": p.max_drawdown_pct,
            "closed_trade_count": p.closed_trade_count,
            "winning_trades": p.winning_trades,
            "losing_trades": p.losing_trades,
            "win_rate_pct": p.win_rate_pct,
            "avg_winner": p.avg_winner,
            "avg_loser": p.avg_loser,
            "persistence_enabled": self.ledger is not None,
            "profitability_enforced": self.profitability_gate.enforce,
            "last_profitability_reason": profitability.reason if profitability else None,
            "last_expected_move_bps": profitability.expected_move_bps if profitability else None,
            "last_minimum_required_bps": (
                profitability.minimum_required_bps if profitability else None
            ),
            "reason": "Paper machine. Public SMA rule. Live execution blocked.",
        }

    async def restore_persisted_state(self) -> None:
        if self.ledger is None:
            return

        state = await self.ledger.load_latest_state(self.symbol)
        if state is None:
            self._log(
                "INFO",
                "No persisted paper state restored.",
                component="database",
                event="restore_empty",
            )
            return

        account = state["account"]
        position = state["position"]
        fills = state["fills"]
        orders = state["orders"]

        closed_pnls = [
            float(row.net_pnl_usd)
            for row in fills
            if row.net_pnl_usd is not None
        ]

        self.mark = float(account.mark) if account.mark is not None else None
        self.portfolio.restore(
            usd=float(account.usd),
            btc=float(account.btc),
            avg_entry=float(position.avg_entry) if position is not None else 0.0,
            entry_fees_open=float(account.entry_fees_open),
            realized_session=float(account.realized_session),
            daily_realized=float(account.daily_realized),
            gross_realized=float(account.gross_realized),
            total_fees=float(account.total_fees),
            total_spread_cost=float(account.total_spread_cost),
            total_slippage_cost=float(account.total_slippage_cost),
            peak_equity=float(position.peak_equity) if position is not None else float(account.equity_usd),
            max_drawdown_pct=float(account.max_drawdown_pct),
            captured_at=account.captured_at,
            closed_trade_pnls=closed_pnls,
            mark=self.mark,
        )

        self.fills.clear()
        for row in fills:
            self.fills.append(
                {
                    "ts_utc": row.occurred_at.isoformat(),
                    "client_order_id": row.client_order_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "qty": row.qty,
                    "reference_price": row.reference_price,
                    "execution_price": row.execution_price,
                    "fee_usd": row.fee_usd,
                    "spread_cost_usd": row.spread_cost_usd,
                    "slippage_cost_usd": row.slippage_cost_usd,
                    "realized_net_pnl_usd": row.net_pnl_usd,
                    "paper_mode": row.paper_mode,
                }
            )

        self.orders.clear()
        for row in orders:
            self.orders.append(
                {
                    "ts_utc": row.created_at.isoformat(),
                    "client_order_id": row.client_order_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "qty": row.qty,
                    "reference_price": row.reference_price,
                    "actor": row.actor,
                    "status": row.status,
                    "paper_mode": row.paper_mode,
                }
            )

        # Restores always fail closed. The operator must arm explicitly.
        self._set_state(BotState.OFFLINE)
        self._log(
            "INFO",
            "Persisted paper ledger restored; bot remains OFFLINE.",
            component="database",
            event="restore_complete",
            payload={
                "orders": len(self.orders),
                "fills": len(self.fills),
                "btc": self.btc,
                "usd": self.usd,
            },
        )

    async def seed_history(self) -> None:
        try:
            prices = await self.market_data.get_seed_prices(self.symbol, limit=120)
            for px in prices:
                self.closes.append(float(px))
            if self.closes:
                self.mark = self.closes[-1]
                self.mark_source = getattr(self.market_data, "source", "provider")
                self._last_tick_mono = time.monotonic()
                self.portfolio.mark_to_market(self.mark)
            self._log(
                "INFO",
                f"Seeded {len(self.closes)} public BTC marks for SMA warm-up.",
                component="market_data",
                event="history_seeded",
                payload={"count": len(self.closes), "source": self.mark_source},
            )
        except Exception as exc:
            self._log(
                "WARN",
                f"History seed failed: {exc}",
                component="market_data",
                event="history_seed_failed",
            )

    def _apply_execution(self, fill: ExecutionResult, actor: str) -> bool:
        applied, error, realized_net = self.portfolio.apply_fill(fill, self.mark)
        if not applied:
            self._log(
                "WARN",
                f"Paper fill rejected by portfolio: {error}",
                actor=actor,
                component="portfolio",
                event="fill_rejected",
                correlation_id=fill.client_order_id,
                payload={"reason": error, "side": fill.side, "qty": fill.qty},
            )
            return False

        if fill.side == "buy":
            self._set_state(BotState.IN_POSITION)
        elif self.portfolio.btc <= 0:
            self._set_state(
                BotState.IDLE if self.state != BotState.OFFLINE.value else BotState.OFFLINE
            )

        fill_record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "client_order_id": fill.client_order_id,
            "symbol": self.symbol,
            "side": fill.side,
            "qty": fill.qty,
            "reference_price": fill.reference_price,
            "execution_price": fill.execution_price,
            "fee_usd": fill.fee_usd,
            "spread_cost_usd": fill.spread_cost_usd,
            "slippage_cost_usd": fill.slippage_cost_usd,
            "realized_net_pnl_usd": realized_net,
            "paper_mode": True,
        }
        self.fills.appendleft(fill_record)

        self._log(
            "FILL",
            (
                f"{actor} {fill.side.upper()} {fill.qty} BTC @ "
                f"{fill.execution_price:.2f} fee {fill.fee_usd:.2f}"
            ),
            actor=actor,
            component="execution",
            event="fill_applied",
            correlation_id=fill.client_order_id,
            payload={
                "side": fill.side,
                "qty": fill.qty,
                "reference_price": fill.reference_price,
                "execution_price": fill.execution_price,
                "fee_usd": fill.fee_usd,
                "spread_cost_usd": fill.spread_cost_usd,
                "slippage_cost_usd": fill.slippage_cost_usd,
                "realized_net_pnl_usd": realized_net,
            },
        )
        return True

    async def _execute(self, side: str, qty: float, actor: str) -> bool:
        if not self.mark:
            return False
        if side == "sell":
            qty = min(qty, self.btc)
            if qty <= 0:
                return False

        request = OrderRequest.market(
            side=side,  # type: ignore[arg-type]
            qty=qty,
            reference_price=self.mark,
            actor=actor,
        )
        self._log(
            "ORDER",
            f"{actor} submitted paper {side} for {qty} BTC",
            actor=actor,
            component="execution",
            event="order_submitted",
            correlation_id=request.client_order_id,
            payload={"side": side, "qty": qty, "reference_price": self.mark},
        )
        fill = await self.execution.execute_market(request)
        applied = self._apply_execution(fill, actor)
        order_record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "client_order_id": request.client_order_id,
            "symbol": self.symbol,
            "side": request.side,
            "qty": request.qty,
            "reference_price": request.reference_price,
            "actor": request.actor,
            "status": "filled" if applied else "rejected",
            "paper_mode": True,
        }
        self.orders.appendleft(order_record)

        if self.ledger is not None:
            await self.ledger.record_order(order_record)
            if applied and self.fills:
                await self.ledger.record_fill(self.fills[0])
                await self.ledger.save_portfolio(
                    symbol=self.symbol,
                    snapshot=self.snapshot(),
                    entry_fees_open=self.portfolio.entry_fees_open,
                )

        return applied

    def _entry_allowed(self, qty: float) -> bool:
        if not self.mark:
            return False

        # The public SMA reference rule intentionally does not invent a forward
        # return estimate. Until a strategy supplies one, profitability remains
        # advisory in paper mode and the missing estimate is visible.
        decision = self.entry_decisions.evaluate(
            expected_move_bps=None,
            reference_price=self.mark,
            qty=qty,
            flatten_lock=self.flatten_lock,
            paper_mode=self.paper_mode,
            live_blocked=self.live_blocked,
            position_btc=self.btc,
            max_position_btc=self.max_position,
            equity=self.equity,
            peak_equity=self.peak_equity,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            daily_realized=self.daily_realized,
            daily_loss_cap=DAILY_LOSS_CAP,
        )
        self.last_profitability = decision.profitability

        if not decision.allowed:
            self._log(
                "WARN",
                f"Buy denied: {decision.reason}",
                component="risk_guard",
                event="entry_denied",
                payload={
                    "reason": decision.reason,
                    "minimum_required_bps": decision.profitability.minimum_required_bps,
                },
            )
            return False

        if decision.profitability.reason == "expected_edge_unavailable":
            self._log(
                "INFO",
                (
                    "Profitability gate advisory only: expected edge unavailable; "
                    f"estimated one-way cost="
                    f"{decision.profitability.costs.total_cost_bps:.2f}bps"
                ),
                component="profitability",
                event="edge_unavailable",
                payload={
                    "estimated_cost_bps": decision.profitability.costs.total_cost_bps,
                    "minimum_required_bps": decision.profitability.minimum_required_bps,
                },
            )
        return True

    async def evaluate_and_maybe_trade(self) -> None:
        if self.state not in (BotState.IDLE.value, BotState.IN_POSITION.value) or not self.mark:
            return

        if self.btc > 0 and self.avg_entry > 0:
            stop = self.avg_entry * (1 - self.stop_loss_pct / 100)
            if self.mark <= stop:
                self._log(
                    "BOT",
                    f"Stop-loss hit at {self.mark:.2f} (stop {stop:.2f}).",
                    actor="bot",
                    component="strategy",
                    event="stop_triggered",
                )
                await self._execute("sell", self.btc, "bot-stop")
                return

        signal = crossover_signal(
            list(self.closes),
            self.short_ma,
            self.long_ma,
            in_position=self.btc > 0,
        )

        if signal == "buy":
            if not self._entry_allowed(self.position_size):
                return

            self._log(
                "BOT",
                f"SMA cross-up. Paper BUY {self.position_size} BTC",
                actor="bot",
                component="strategy",
                event="entry_signal",
            )
            await self._execute("buy", self.position_size, "bot")

        elif signal == "sell" and self.btc > 0:
            self._log(
                "BOT",
                "SMA cross-down. Paper SELL inventory",
                actor="bot",
                component="strategy",
                event="exit_signal",
            )
            await self._execute("sell", self.btc, "bot")

    async def tick(self) -> None:
        try:
            snapshot = await self.market_data.get_mark(self.symbol)
        except Exception as exc:
            self._consecutive_mark_failures += 1
            self._log(
                "WARN",
                f"Mark fetch failed: {exc}",
                component="market_data",
                event="mark_fetch_failed",
                payload={"consecutive_failures": self._consecutive_mark_failures},
            )
            if self._consecutive_mark_failures >= MAX_CONSECUTIVE_MARK_FAILURES:
                async with self._lock:
                    if self.state != BotState.FAULT.value:
                        self._trip_market_data_kill_switch("mark_fetch_failure_threshold")
            return

        if snapshot is None:
            self._consecutive_mark_failures += 1
            self._log(
                "WARN",
                "Market data provider returned no fresh mark.",
                component="market_data",
                event="mark_unavailable",
                payload={"consecutive_failures": self._consecutive_mark_failures},
            )
            if self._consecutive_mark_failures >= MAX_CONSECUTIVE_MARK_FAILURES:
                async with self._lock:
                    if self.state != BotState.FAULT.value:
                        self._trip_market_data_kill_switch("mark_unavailable_threshold")
            return

        async with self._lock:
            self._consecutive_mark_failures = 0
            self.mark = snapshot.price
            self.mark_source = snapshot.source
            self.closes.append(snapshot.price)
            self._last_tick_mono = time.monotonic()
            self.portfolio.mark_to_market(self.mark)
            await self.evaluate_and_maybe_trade()

    async def loop(self) -> None:
        await self.restore_persisted_state()
        await self.seed_history()
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self._log(
                    "ERROR",
                    f"Tick fault: {exc}",
                    component="scheduler",
                    event="tick_fault",
                )
            await asyncio.sleep(POLL_SECONDS)

    def start_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop())

    async def start_bot(self) -> dict[str, Any]:
        async with self._lock:
            if self.flatten_lock:
                return {"ok": False, "error": "flatten_lock"}
            if self.state == BotState.FAULT.value:
                return {"ok": False, "error": "fault_requires_reset"}
            self._set_state(
                BotState.IN_POSITION if self.btc > 0 else BotState.IDLE
            )
            self._log(
                "INFO",
                f"Bot armed ({self.state}).",
                actor="operator",
                component="engine",
                event="bot_armed",
            )
            return {"ok": True, **self.snapshot()}

    async def stop_bot(self) -> dict[str, Any]:
        async with self._lock:
            self._set_state(BotState.OFFLINE)
            self._log(
                "INFO",
                "Bot disarmed. Position left untouched.",
                actor="operator",
                component="engine",
                event="bot_disarmed",
            )
            return {"ok": True, **self.snapshot()}

    async def manual(self, side: str, qty: float | None = None) -> dict[str, Any]:
        async with self._lock:
            if not self.mark:
                return {"ok": False, "error": "no_mark"}

            qty = qty or self.position_size
            if side == "buy":
                reason = deny_entry(
                    flatten_lock=self.flatten_lock,
                    paper_mode=True,
                    live_blocked=True,
                    qty=qty,
                    position_btc=self.btc,
                    max_position_btc=self.max_position,
                    equity=self.equity,
                    peak_equity=self.peak_equity,
                    max_drawdown_pct=MAX_DRAWDOWN_PCT,
                    daily_realized=self.daily_realized,
                    daily_loss_cap=DAILY_LOSS_CAP,
                )
                if reason:
                    return {"ok": False, "error": reason}

            await self._execute(side, qty, "operator")
            return {"ok": True, **self.snapshot()}

    async def flatten(self) -> dict[str, Any]:
        async with self._lock:
            self.flatten_lock = True
            if self.btc > 0 and self.mark:
                await self._execute("sell", self.btc, "flatten")
            self._set_state(BotState.OFFLINE)
            self._log(
                "INFO",
                "Emergency flatten complete. Entries locked.",
                actor="operator",
                component="risk_guard",
                event="flatten_complete",
            )
            return {"ok": True, **self.snapshot()}

    async def unlock(self) -> dict[str, Any]:
        async with self._lock:
            if self.state == BotState.FAULT.value:
                return {"ok": False, "error": "fault_requires_reset"}
            self.flatten_lock = False
            self._log(
                "INFO",
                "Flatten lock cleared by operator.",
                actor="operator",
                component="risk_guard",
                event="flatten_lock_cleared",
            )
            return {"ok": True, **self.snapshot()}

    async def reset_fault(self) -> dict[str, Any]:
        async with self._lock:
            if self.state != BotState.FAULT.value:
                return {"ok": False, "error": "not_in_fault"}

            age = None
            if self._last_tick_mono is not None:
                age = int((time.monotonic() - self._last_tick_mono) * 1000)

            if (
                self.mark is None
                or age is None
                or age > MAX_MARK_AGE_MS
                or self._consecutive_mark_failures > 0
            ):
                return {"ok": False, "error": "market_data_not_fresh"}

            self._set_state(BotState.OFFLINE)
            self.flatten_lock = False
            self._log(
                "INFO",
                "FAULT reset after fresh market data verification; bot remains OFFLINE.",
                actor="operator",
                component="risk_guard",
                event="fault_reset",
            )
            return {"ok": True, **self.snapshot()}


engine = PaperEngine()
