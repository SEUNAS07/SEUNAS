"""Run a strategy over historical candles and report performance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .broker import PaperBroker
from .data import Candle
from .engine import EnginePoint, Trade, TradingEngine
from .risk import RiskConfig, RiskManager
from .strategies import Strategy


@dataclass
class BacktestResult:
    starting_cash: float
    final_equity: float
    trades: list[Trade]
    equity_curve: list[EnginePoint]
    periods_per_year: float
    buy_and_hold_return: float

    @property
    def total_return(self) -> float:
        return self.final_equity / self.starting_cash - 1

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        return sum(t.pnl > 0 for t in closed) / len(closed) if closed else 0.0

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl for t in self.closed_trades if t.pnl > 0)
        losses = -sum(t.pnl for t in self.closed_trades if t.pnl < 0)
        if losses == 0:
            return math.inf if gains > 0 else 0.0
        return gains / losses

    @property
    def max_drawdown(self) -> float:
        peak, worst = -math.inf, 0.0
        for p in self.equity_curve:
            peak = max(peak, p.equity)
            if peak > 0:
                worst = min(worst, p.equity / peak - 1)
        return worst

    @property
    def sharpe(self) -> float:
        eq = [p.equity for p in self.equity_curve]
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        return mean / sd * math.sqrt(self.periods_per_year) if sd > 0 else 0.0

    def summary(self) -> dict[str, float | int | str]:
        return {
            "starting_cash": round(self.starting_cash, 2),
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return * 100, 2),
            "buy_and_hold_pct": round(self.buy_and_hold_return * 100, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "sharpe": round(self.sharpe, 2),
            "trades": len(self.closed_trades),
            "win_rate_pct": round(self.win_rate * 100, 1),
            "profit_factor": round(self.profit_factor, 2) if math.isfinite(self.profit_factor) else "inf",
        }

    def report(self) -> str:
        lines = [f"{k:>18}: {v}" for k, v in self.summary().items()]
        return "\n".join(lines)


def run_backtest(
    candles: Sequence[Candle],
    strategy: Strategy,
    risk_cfg: RiskConfig | None = None,
    starting_cash: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 5.0,
    periods_per_year: float = 365 * 24,
    symbol: str = "SYNTH/USD",
) -> BacktestResult:
    if len(candles) < 2:
        raise ValueError("need at least 2 candles to backtest")
    broker = PaperBroker(symbol, starting_cash, fee_rate, slippage_bps)
    engine = TradingEngine(strategy, broker, RiskManager(risk_cfg or RiskConfig()))
    for candle in candles:
        engine.execute_pending(candle.open, candle.timestamp)
        engine.check_exits(candle)
        engine.on_close(candle)
    last = candles[-1]
    if engine.in_position:
        engine._exit(last.close, last.timestamp, "end of data")
        engine.equity_curve[-1] = EnginePoint(last.timestamp, broker.equity(last.close), last.close)
    return BacktestResult(
        starting_cash=starting_cash,
        final_equity=broker.equity(last.close),
        trades=engine.trades,
        equity_curve=engine.equity_curve,
        periods_per_year=periods_per_year,
        buy_and_hold_return=last.close / candles[0].open - 1,
    )
