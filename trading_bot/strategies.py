"""Trading strategies. Each turns a history of closed candles into a signal."""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from .data import Candle
from .indicators import ema, rsi, sma


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Strategy:
    """Base class. ``generate`` sees only candles that have already closed."""

    name = "base"

    @property
    def warmup(self) -> int:
        """Minimum number of candles before signals are meaningful."""
        return 1

    def generate(self, candles: Sequence[Candle], in_position: bool) -> Signal:
        raise NotImplementedError


class SmaCrossover(Strategy):
    """Go long when the fast moving average crosses above the slow one; exit on the reverse."""

    name = "sma_crossover"

    def __init__(self, fast: int = 20, slow: int = 50, use_ema: bool = False):
        if fast >= slow:
            raise ValueError("fast period must be shorter than slow period")
        self.fast, self.slow, self.use_ema = fast, slow, use_ema

    @property
    def warmup(self) -> int:
        return self.slow + 1

    def generate(self, candles, in_position):
        if len(candles) < self.warmup:
            return Signal.HOLD
        closes = [c.close for c in candles[-(self.slow + 50):]]
        ma = ema if self.use_ema else sma
        f, s = ma(closes, self.fast), ma(closes, self.slow)
        if None in (f[-1], s[-1], f[-2], s[-2]):
            return Signal.HOLD
        crossed_up = f[-2] <= s[-2] and f[-1] > s[-1]
        crossed_down = f[-2] >= s[-2] and f[-1] < s[-1]
        if crossed_up and not in_position:
            return Signal.BUY
        if crossed_down and in_position:
            return Signal.SELL
        return Signal.HOLD


class RsiMeanReversion(Strategy):
    """Buy when RSI is oversold (optionally only above a trend filter); sell when overbought."""

    name = "rsi_mean_reversion"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70, trend_sma: int = 0):
        if not 0 < oversold < overbought < 100:
            raise ValueError("require 0 < oversold < overbought < 100")
        self.period, self.oversold, self.overbought, self.trend_sma = period, oversold, overbought, trend_sma

    @property
    def warmup(self) -> int:
        return max(self.period + 1, self.trend_sma)

    def generate(self, candles, in_position):
        if len(candles) < self.warmup:
            return Signal.HOLD
        closes = [c.close for c in candles[-(self.warmup + 200):]]
        r = rsi(closes, self.period)[-1]
        if r is None:
            return Signal.HOLD
        if not in_position and r < self.oversold:
            if self.trend_sma:
                trend = sma(closes, self.trend_sma)[-1]
                if trend is None or closes[-1] < trend:
                    return Signal.HOLD
            return Signal.BUY
        if in_position and r > self.overbought:
            return Signal.SELL
        return Signal.HOLD


STRATEGIES: dict[str, type[Strategy]] = {
    SmaCrossover.name: SmaCrossover,
    RsiMeanReversion.name: RsiMeanReversion,
}


def build_strategy(name: str, params: dict | None = None) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy {name!r}; available: {sorted(STRATEGIES)}") from exc
    return cls(**(params or {}))
