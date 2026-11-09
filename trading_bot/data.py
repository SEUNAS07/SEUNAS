"""Market data: candle type, CSV loading, synthetic data and live exchange feeds."""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


@dataclass(frozen=True)
class Candle:
    timestamp: int  # milliseconds since epoch (UTC), candle open time
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)


def timeframe_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}; use one of {sorted(TIMEFRAME_SECONDS)}"
        ) from exc


def periods_per_year(timeframe: str) -> float:
    return 365 * 86400 / timeframe_seconds(timeframe)


def _parse_timestamp(raw: str) -> int:
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        value = int(raw)
        # Treat 10-digit values as seconds, otherwise milliseconds.
        return value * 1000 if abs(value) < 10**11 else value
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def load_csv(path: str | Path) -> list[Candle]:
    """Load OHLCV candles from a CSV with a header row.

    Required columns (case-insensitive): timestamp (or date/time), open, high,
    low, close. ``volume`` is optional. Timestamps may be epoch seconds, epoch
    milliseconds or ISO-8601 strings.
    """
    candles: list[Candle] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: empty CSV")
        cols = {name.strip().lower(): name for name in reader.fieldnames}
        ts_col = next((cols[c] for c in ("timestamp", "date", "time", "datetime") if c in cols), None)
        missing = [c for c in ("open", "high", "low", "close") if c not in cols]
        if ts_col is None or missing:
            raise ValueError(f"{path}: missing columns {missing or ['timestamp']}")
        for row in reader:
            candles.append(
                Candle(
                    timestamp=_parse_timestamp(row[ts_col]),
                    open=float(row[cols["open"]]),
                    high=float(row[cols["high"]]),
                    low=float(row[cols["low"]]),
                    close=float(row[cols["close"]]),
                    volume=float(row[cols["volume"]]) if "volume" in cols and row[cols["volume"]] else 0.0,
                )
            )
    candles.sort(key=lambda c: c.timestamp)
    return candles


def save_csv(candles: Iterable[Candle], path: str | Path) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([c.timestamp, c.open, c.high, c.low, c.close, c.volume])


def synthetic_candles(
    n: int = 2000,
    start_price: float = 100.0,
    timeframe: str = "1h",
    seed: int | None = 42,
    volatility: float = 0.01,
    start_ts: int = 1_700_000_000_000,
) -> list[Candle]:
    """Generate random-walk candles with drifting trend regimes.

    Useful for smoke-testing strategies without a data source. It is *not*
    a model of any real market: good results on it mean nothing.
    """
    rng = random.Random(seed)
    step_ms = timeframe_seconds(timeframe) * 1000
    price = start_price
    drift = 0.0
    candles = []
    for i in range(n):
        if i % 150 == 0:
            drift = rng.uniform(-0.002, 0.002)
        open_ = price
        ret = drift + volatility * rng.gauss(0, 1)
        close = max(0.01, open_ * math.exp(ret))
        wiggle = abs(rng.gauss(0, volatility / 2))
        high = max(open_, close) * (1 + wiggle)
        low = min(open_, close) * (1 - wiggle)
        candles.append(
            Candle(
                timestamp=start_ts + i * step_ms,
                open=round(open_, 6),
                high=round(high, 6),
                low=round(low, 6),
                close=round(close, 6),
                volume=round(rng.uniform(100, 1000), 2),
            )
        )
        price = close
    return candles


class CcxtFeed:
    """Fetch closed OHLCV candles from any exchange supported by ccxt."""

    def __init__(self, exchange_id: str, symbol: str, timeframe: str, exchange=None):
        if exchange is None:
            try:
                import ccxt  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError("ccxt is required for exchange data: pip install ccxt") from exc
            exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self._tf_ms = timeframe_seconds(timeframe) * 1000

    def fetch_closed(self, limit: int = 300, now_ms: int | None = None) -> list[Candle]:
        rows = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
        if now_ms is None:
            now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        candles = [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)) for r in rows]
        # Drop the still-forming candle so signals are only computed on closed bars.
        return [c for c in candles if c.timestamp + self._tf_ms <= now_ms]

    def last_price(self) -> float:
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker["last"])
