"""Polling loop for paper trading on live data and for real live trading."""

from __future__ import annotations

import csv
import logging
import os
import time
from datetime import datetime, timezone

from .broker import Broker
from .data import CcxtFeed
from .engine import TradingEngine

log = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


class Journal:
    """Append every closed trade to a CSV file."""

    FIELDS = ["entry_time", "exit_time", "qty", "entry_price", "exit_price", "pnl", "reason"]

    def __init__(self, path: str):
        self.path = path
        if not os.path.exists(path):
            with open(path, "w", newline="") as fh:
                csv.writer(fh).writerow(self.FIELDS)

    def record(self, trade) -> None:
        iso = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
        with open(self.path, "a", newline="") as fh:
            csv.writer(fh).writerow([
                iso(trade.entry_ts), iso(trade.exit_ts), trade.qty,
                trade.entry_price, trade.exit_price, round(trade.pnl, 6), trade.exit_reason,
            ])


def run_loop(engine: TradingEngine, feed: CcxtFeed, broker: Broker, poll_seconds: int, journal: Journal,
              max_iterations: int | None = None) -> None:
    """Warm up on history, then on each poll process new closed candles and
    check stops against the latest price. Ctrl+C stops the loop."""
    history = feed.fetch_closed(limit=max(engine.history_limit, 300))
    if not history:
        raise RuntimeError("exchange returned no closed candles")
    for c in history[:-1]:
        engine.on_close(c)
    engine.pending = engine.pending.HOLD  # never act on stale historical signals
    last_ts = history[-2].timestamp if len(history) > 1 else 0
    engine.adopt_existing_position()
    log.info("Warmed up on %d candles; equity %.2f", len(history) - 1, broker.equity(history[-1].close))

    journaled = sum(1 for t in engine.trades if not t.is_open)
    i = 0
    try:
        while max_iterations is None or i < max_iterations:
            i += 1
            try:
                now = _now_ms()
                price = feed.last_price()
                engine.check_exits_live(price, now)
                for candle in feed.fetch_closed(limit=10, now_ms=now):
                    if candle.timestamp <= last_ts:
                        continue
                    last_ts = candle.timestamp
                    signal = engine.on_close(candle)
                    log.info("%s close %.4f -> %s | equity %.2f", candle.dt.isoformat(), candle.close,
                             signal.value, broker.equity(candle.close))
                    engine.execute_pending(price, now)
                closed = [t for t in engine.trades if not t.is_open]
                for t in closed[journaled:]:
                    journal.record(t)
                journaled = len(closed)
            except KeyboardInterrupt:
                raise
            except Exception:  # network hiccups etc. must not kill the bot
                log.exception("Loop iteration failed; retrying next poll")
            if max_iterations is None or i < max_iterations:
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        log.info("Stopped by user. Open position (if any) is left as-is: %.6f", broker.position())
