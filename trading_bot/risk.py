"""Position sizing and account-level safety limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01  # fraction of equity lost if the stop is hit
    atr_period: int = 14
    atr_stop_mult: float = 2.0  # stop distance = ATR * mult
    take_profit_r: float = 0.0  # take profit at R multiple of stop distance; 0 disables
    max_position_pct: float = 0.25  # cap position notional as fraction of equity
    max_daily_loss_pct: float = 0.03  # stop opening trades after losing this much in a UTC day
    max_drawdown_pct: float = 0.20  # halt the bot entirely past this drawdown from peak

    def validate(self) -> None:
        checks = {
            "risk_per_trade": 0 < self.risk_per_trade <= 0.1,
            "atr_stop_mult": self.atr_stop_mult > 0,
            "take_profit_r": self.take_profit_r >= 0,
            "max_position_pct": 0 < self.max_position_pct <= 1,
            "max_daily_loss_pct": 0 < self.max_daily_loss_pct <= 1,
            "max_drawdown_pct": 0 < self.max_drawdown_pct <= 1,
            "atr_period": self.atr_period > 0,
        }
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            raise ValueError(f"Invalid risk settings: {bad}")


@dataclass
class TradePlan:
    qty: float
    stop: float
    take_profit: Optional[float]


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        cfg.validate()
        self.cfg = cfg
        self.peak_equity: Optional[float] = None
        self.day: Optional[int] = None
        self.day_start_equity: Optional[float] = None
        self.halted_reason: Optional[str] = None

    def update_equity(self, equity: float, timestamp_ms: int) -> None:
        day = timestamp_ms // 86_400_000
        if self.day != day:
            self.day, self.day_start_equity = day, equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity and equity < self.peak_equity * (1 - self.cfg.max_drawdown_pct):
            self.halted_reason = (
                f"max drawdown {self.cfg.max_drawdown_pct:.0%} breached "
                f"(peak {self.peak_equity:.2f}, now {equity:.2f})"
            )

    def can_open(self, equity: float) -> tuple[bool, str]:
        if self.halted_reason:
            return False, self.halted_reason
        if self.day_start_equity and equity < self.day_start_equity * (1 - self.cfg.max_daily_loss_pct):
            return False, f"daily loss limit {self.cfg.max_daily_loss_pct:.0%} reached"
        return True, ""

    def plan(self, equity: float, cash: float, price: float, atr_value: Optional[float]) -> Optional[TradePlan]:
        """Size a long entry. Returns None if no sensible trade can be made."""
        if price <= 0 or atr_value is None or atr_value <= 0:
            return None
        stop_dist = atr_value * self.cfg.atr_stop_mult
        stop = price - stop_dist
        if stop <= 0:
            return None
        qty_by_risk = equity * self.cfg.risk_per_trade / stop_dist
        qty_by_cap = equity * self.cfg.max_position_pct / price
        qty_by_cash = cash * 0.99 / price  # leave headroom for fees/slippage
        qty = min(qty_by_risk, qty_by_cap, qty_by_cash)
        if qty <= 0:
            return None
        tp = price + stop_dist * self.cfg.take_profit_r if self.cfg.take_profit_r > 0 else None
        return TradePlan(qty=qty, stop=stop, take_profit=tp)
