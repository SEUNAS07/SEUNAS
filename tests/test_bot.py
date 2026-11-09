import math
import os
import tempfile
import unittest

from trading_bot.backtest import run_backtest
from trading_bot.broker import PaperBroker
from trading_bot.cli import main
from trading_bot.config import load_config
from trading_bot.data import Candle, load_csv, save_csv, synthetic_candles
from trading_bot.engine import TradingEngine
from trading_bot.indicators import atr, ema, rsi, sma
from trading_bot.risk import RiskConfig, RiskManager
from trading_bot.strategies import RsiMeanReversion, Signal, SmaCrossover, Strategy, build_strategy


def bar(i, o, h, l, c):
    return Candle(1_700_000_000_000 + i * 3_600_000, o, h, l, c, 1)


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])

    def test_ema_seeds_with_sma(self):
        out = ema([1, 2, 3, 4], 3)
        self.assertEqual(out[:3], [None, None, 2])
        self.assertAlmostEqual(out[3], 3.0)

    def test_rsi_extremes(self):
        self.assertEqual(rsi(list(range(1, 30)), 14)[-1], 100.0)
        self.assertEqual(rsi(list(range(30, 1, -1)), 14)[-1], 0.0)

    def test_atr_constant_range(self):
        n = 30
        out = atr([11] * n, [9] * n, [10] * n, 14)
        self.assertAlmostEqual(out[-1], 2.0)


class StrategyTests(unittest.TestCase):
    def test_sma_crossover_buy_then_sell(self):
        prices = [10] * 10 + [11, 12, 13] + [9, 8, 7]
        candles = [bar(i, p, p, p, p) for i, p in enumerate(prices)]
        s = SmaCrossover(fast=2, slow=5)
        signals = [s.generate(candles[: i + 1], in_position=False) for i in range(len(candles))]
        self.assertIn(Signal.BUY, signals)
        sells = [s.generate(candles[: i + 1], in_position=True) for i in range(len(candles))]
        self.assertIn(Signal.SELL, sells)

    def test_build_strategy_validates(self):
        with self.assertRaises(ValueError):
            build_strategy("nope")
        with self.assertRaises(ValueError):
            SmaCrossover(fast=50, slow=20)
        with self.assertRaises(ValueError):
            RsiMeanReversion(oversold=80, overbought=20)


class BrokerTests(unittest.TestCase):
    def test_paper_round_trip_costs(self):
        b = PaperBroker("X/USD", 1000, fee_rate=0.001, slippage_bps=10)
        buy = b.buy(1, 100, 0)
        self.assertAlmostEqual(buy.price, 100.1)
        sell = b.sell(1, 100, 1)
        self.assertAlmostEqual(sell.price, 99.9)
        self.assertLess(b.cash(), 1000)
        self.assertEqual(b.position(), 0)

    def test_cannot_overspend(self):
        b = PaperBroker("X/USD", 100, fee_rate=0.0, slippage_bps=0)
        fill = b.buy(5, 100, 0)
        self.assertAlmostEqual(fill.qty, 1.0)
        self.assertGreaterEqual(b.cash(), -1e-9)


class RiskTests(unittest.TestCase):
    def test_sizing_respects_all_caps(self):
        rm = RiskManager(RiskConfig(risk_per_trade=0.01, atr_stop_mult=2, max_position_pct=0.25))
        plan = rm.plan(equity=10_000, cash=10_000, price=100, atr_value=1)
        # risk cap: 100 / 2 = 50 units = $5000; position cap: $2500 = 25 units
        self.assertAlmostEqual(plan.qty, 25)
        self.assertAlmostEqual(plan.stop, 98)

    def test_daily_loss_and_drawdown_halt(self):
        rm = RiskManager(RiskConfig(max_daily_loss_pct=0.05, max_drawdown_pct=0.10))
        rm.update_equity(1000, 0)
        self.assertTrue(rm.can_open(1000)[0])
        self.assertFalse(rm.can_open(940)[0])
        rm.update_equity(880, 1000)
        self.assertIsNotNone(rm.halted_reason)

    def test_invalid_config(self):
        with self.assertRaises(ValueError):
            RiskConfig(risk_per_trade=0.5).validate()


class AlwaysBuy(Strategy):
    name = "always_buy"

    def generate(self, candles, in_position):
        return Signal.HOLD if in_position else Signal.BUY


class EngineTests(unittest.TestCase):
    def _engine(self, **risk):
        broker = PaperBroker("X/USD", 10_000, fee_rate=0, slippage_bps=0)
        cfg = RiskConfig(atr_period=3, **risk)
        return TradingEngine(AlwaysBuy(), broker, RiskManager(cfg)), broker

    def test_fills_at_next_open_not_signal_close(self):
        engine, broker = self._engine()
        candles = [bar(i, 100, 101, 99, 100) for i in range(5)] + [bar(5, 105, 106, 104, 105)]
        for c in candles:
            engine.execute_pending(c.open, c.timestamp)
            engine.check_exits(c)
            engine.on_close(c)
        self.assertEqual(engine.trades[0].entry_price, 100)  # first entry on bar after ATR warm-up
        self.assertGreater(broker.position(), 0)

    def test_stop_loss_and_gap(self):
        engine, broker = self._engine(atr_stop_mult=1)
        for i in range(5):
            c = bar(i, 100, 101, 99, 100)
            engine.execute_pending(c.open, c.timestamp)
            engine.check_exits(c)
            engine.on_close(c)
        t = engine.open_trade
        self.assertIsNotNone(t)
        gap = bar(6, t.stop - 5, t.stop - 4, t.stop - 6, t.stop - 5)
        engine.check_exits(gap)
        self.assertEqual(t.exit_reason, "stop (gap)")
        self.assertEqual(t.exit_price, gap.open)
        self.assertEqual(broker.position(), 0)


class BacktestTests(unittest.TestCase):
    def test_runs_and_is_deterministic(self):
        candles = synthetic_candles(1500, seed=7)
        r1 = run_backtest(candles, SmaCrossover(10, 30))
        r2 = run_backtest(candles, SmaCrossover(10, 30))
        self.assertEqual(r1.summary(), r2.summary())
        self.assertGreater(len(r1.closed_trades), 0)
        self.assertLessEqual(r1.max_drawdown, 0)
        self.assertTrue(math.isfinite(r1.sharpe))
        self.assertFalse(any(t.is_open for t in r1.trades))

    def test_equity_matches_trade_pnl(self):
        candles = synthetic_candles(1500, seed=3)
        r = run_backtest(candles, RsiMeanReversion())
        self.assertAlmostEqual(r.final_equity - r.starting_cash, sum(t.pnl for t in r.trades), places=6)


class IoTests(unittest.TestCase):
    def test_csv_round_trip_and_iso_timestamps(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.csv")
            candles = synthetic_candles(20)
            save_csv(candles, path)
            self.assertEqual(load_csv(path), candles)
            iso = os.path.join(d, "iso.csv")
            with open(iso, "w") as fh:
                fh.write("Date,Open,High,Low,Close\n2024-01-02,2,3,1,2.5\n2024-01-01,1,2,0.5,1.5\n")
            loaded = load_csv(iso)
            self.assertEqual([c.close for c in loaded], [1.5, 2.5])

    def test_example_config_loads(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(root, "config.example.toml"))
        self.assertEqual(cfg.symbol, "BTC/USDT")
        self.assertTrue(cfg.sandbox)

    def test_cli_backtest(self):
        self.assertEqual(main(["backtest", "--synthetic", "800", "--strategy", "sma_crossover",
                               "--param", "fast=5", "--param", "slow=20"]), 0)

    def test_live_requires_explicit_opt_in(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            import ccxt  # noqa: F401
        except ImportError:
            self.skipTest("ccxt not installed")
        self.assertEqual(main(["live", "--config", os.path.join(root, "config.example.toml")]), 2)


if __name__ == "__main__":
    unittest.main()


class FakeExchange:
    """Stands in for a ccxt exchange: serves synthetic candles one bar at a time."""

    def __init__(self, candles, visible):
        self.candles, self.visible = candles, visible

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        self.visible += 1  # each poll, one more bar has closed
        rows = self.candles[: self.visible]
        return [[c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in rows[-limit:]]

    def fetch_ticker(self, symbol):
        return {"last": self.candles[min(self.visible, len(self.candles) - 1)].open}


class LiveLoopTests(unittest.TestCase):
    def test_paper_loop_with_fake_exchange(self):
        from trading_bot.data import CcxtFeed
        from trading_bot.live import Journal, run_loop

        candles = synthetic_candles(900, seed=11)
        fake = FakeExchange(candles, visible=200)
        feed = CcxtFeed("fake", "X/USD", "1h", exchange=fake)
        feed.fetch_closed = (lambda orig: (lambda limit=300, now_ms=None: orig(limit, now_ms=10**15)))(feed.fetch_closed)
        broker = PaperBroker("X/USD", 10_000, 0.001, 5)
        engine = TradingEngine(SmaCrossover(5, 20), broker, RiskManager(RiskConfig()))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "trades.csv")
            run_loop(engine, feed, broker, poll_seconds=0, journal=Journal(path), max_iterations=600)
            with open(path) as fh:
                rows = fh.read().strip().splitlines()
        closed = [t for t in engine.trades if not t.is_open]
        self.assertGreater(len(closed), 0)
        self.assertEqual(len(rows) - 1, len(closed))
