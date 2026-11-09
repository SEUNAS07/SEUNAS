"""Trading engine: ties strategy, risk manager and broker together.

The same engine drives backtests and live/paper loops. Signals are computed
only on *closed* candles and executed afterwards (at the next bar's open in a
backtest, at the current market price when running live), so a backtest never
trades on information it could not have had.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .broker import Broker, Fill
from .data import Candle
from .indicators import atr
from .risk import RiskManager
from .strategies import Signal, Strategy

log = logging.getLogger(__name__)


@dataclass
class Trade:
    entry_ts: int
    entry_price: float
    qty: float
    entry_fee: float
    stop: float
    take_profit: Optional[float]
    exit_ts: Optional[int] = None
    exit_price: Optional[float] = None
    exit_fee: float = 0.0
    exit_reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.exit_ts is None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.qty - self.entry_fee - self.exit_fee

    @property
    def return_pct(self) -> float:
        cost = self.entry_price * self.qty + self.entry_fee
        return self.pnl / cost if cost else 0.0


@dataclass
class EnginePoint:
    timestamp: int
    equity: float
    price: float


class TradingEngine:
    def __init__(self, strategy: Strategy, broker: Broker, risk: RiskManager, history_limit: int = 1000):
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        self.history: list[Candle] = []
        self.history_limit = max(history_limit, strategy.warmup + risk.cfg.atr_period * 5 + 10)
        self.pending: Signal = Signal.HOLD
        self.pending_atr: Optional[float] = None
        self.trades: list[Trade] = []
        self.equity_curve: list[EnginePoint] = []
        self.events: list[str] = []

    # -- state -----------------------------------------------------------
    @property
    def open_trade(self) -> Optional[Trade]:
        if self.trades and self.trades[-1].is_open:
            return self.trades[-1]
        return None

    @property
    def in_position(self) -> bool:
        return self.broker.position() > 0

    def _note(self, msg: str) -> None:
        self.events.append(msg)
        log.info(msg)

    def _current_atr(self) -> Optional[float]:
        n = self.risk.cfg.atr_period
        window = self.history[-(n * 10):]
        values = atr([c.high for c in window], [c.low for c in window], [c.close for c in window], n)
        return values[-1] if values else None

    def adopt_existing_position(self) -> None:
        """When starting live with coins already held, protect them with an ATR stop."""
        qty = self.broker.position()
        if qty <= 0 or self.open_trade or not self.history:
            return
        price = self.history[-1].close
        a = self._current_atr()
        stop = price - a * self.risk.cfg.atr_stop_mult if a else price * 0.9
        self.trades.append(Trade(self.history[-1].timestamp, price, qty, 0.0, stop, None))
        self._note(f"Adopted existing position of {qty} with stop {stop:.4f}")

    # -- the three phases of a bar -------------------------------------
    def execute_pending(self, price: float, timestamp: int) -> Optional[Fill]:
        """Act on the signal from the last closed bar at ``price``."""
        signal, self.pending = self.pending, Signal.HOLD
        if signal is Signal.BUY and not self.in_position:
            equity = self.broker.equity(price)
            ok, why = self.risk.can_open(equity)
            if not ok:
                self._note(f"Entry skipped: {why}")
                return None
            plan = self.risk.plan(equity, self.broker.cash(), price, self.pending_atr)
            if plan is None:
                self._note("Entry skipped: could not size position")
                return None
            fill = self.broker.buy(plan.qty, price, timestamp)
            if fill:
                # Re-anchor stop/target to the actual fill price.
                dist = price - plan.stop
                tp = fill.price + dist * self.risk.cfg.take_profit_r if plan.take_profit else None
                self.trades.append(Trade(timestamp, fill.price, fill.qty, fill.fee, fill.price - dist, tp))
                self._note(f"BUY {fill.qty:.6f} @ {fill.price:.4f} stop {fill.price - dist:.4f}")
            return fill
        if signal is Signal.SELL and self.in_position:
            return self._exit(price, timestamp, "signal")
        return None

    def check_exits(self, candle: Candle) -> Optional[Fill]:
        """Simulate stop-loss / take-profit hits within a bar (backtest).

        Stops are checked before targets, which is the conservative assumption
        when a single bar touches both.
        """
        t = self.open_trade
        if not t or not self.in_position:
            return None
        if candle.open <= t.stop:
            return self._exit(candle.open, candle.timestamp, "stop (gap)")
        if candle.low <= t.stop:
            return self._exit(t.stop, candle.timestamp, "stop")
        if t.take_profit is not None:
            if candle.open >= t.take_profit:
                return self._exit(candle.open, candle.timestamp, "target (gap)")
            if candle.high >= t.take_profit:
                return self._exit(t.take_profit, candle.timestamp, "target")
        return None

    def check_exits_live(self, price: float, timestamp: int) -> Optional[Fill]:
        """Stop / target check against a live price."""
        t = self.open_trade
        if not t or not self.in_position:
            return None
        if price <= t.stop:
            return self._exit(price, timestamp, "stop")
        if t.take_profit is not None and price >= t.take_profit:
            return self._exit(price, timestamp, "target")
        return None

    def on_close(self, candle: Candle) -> Signal:
        """Record a closed candle, update risk state and queue the next action."""
        self.history.append(candle)
        if len(self.history) > self.history_limit:
            del self.history[: len(self.history) - self.history_limit]
        equity = self.broker.equity(candle.close)
        self.risk.update_equity(equity, candle.timestamp)
        self.equity_curve.append(EnginePoint(candle.timestamp, equity, candle.close))

        if self.risk.halted_reason and self.in_position:
            self._note(f"HALT: {self.risk.halted_reason}; flattening")
            self.pending = Signal.SELL
            return self.pending

        signal = self.strategy.generate(self.history, self.in_position)
        if signal is not Signal.HOLD:
            self.pending = signal
            self.pending_atr = self._current_atr()
        return signal

    def _exit(self, price: float, timestamp: int, reason: str) -> Optional[Fill]:
        fill = self.broker.sell(self.broker.position(), price, timestamp)
        if not fill:
            return None
        t = self.open_trade
        if t:
            t.exit_ts, t.exit_price, t.exit_fee, t.exit_reason = timestamp, fill.price, fill.fee, reason
            self._note(f"SELL {fill.qty:.6f} @ {fill.price:.4f} ({reason}) pnl {t.pnl:+.2f}")
        self.pending = Signal.HOLD
        return fill
