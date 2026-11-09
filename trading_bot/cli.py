"""Command-line entry point: ``python -m trading_bot <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .backtest import run_backtest
from .config import load_config
from .data import load_csv, periods_per_year, save_csv, synthetic_candles
from .strategies import STRATEGIES, build_strategy


def _parse_params(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--param expects key=value, got {pair!r}")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out


def cmd_backtest(args) -> int:
    cfg = load_config(args.config)
    if args.csv:
        candles = load_csv(args.csv)
        source = args.csv
    else:
        candles = synthetic_candles(n=args.synthetic, timeframe=cfg.timeframe, seed=args.seed)
        source = f"synthetic ({args.synthetic} candles, seed {args.seed})"
    params = {**cfg.strategy_params, **_parse_params(args.param)}
    strategy = build_strategy(args.strategy or cfg.strategy, params)
    result = run_backtest(
        candles, strategy, cfg.risk,
        starting_cash=cfg.starting_cash, fee_rate=cfg.fee_rate, slippage_bps=cfg.slippage_bps,
        periods_per_year=periods_per_year(cfg.timeframe), symbol=cfg.symbol,
    )
    print(f"Backtest: {strategy.name} {params or ''} on {source}")
    print(result.report())
    if args.trades:
        print("\nTrades:")
        for t in result.closed_trades:
            print(f"  {t.entry_price:>12.4f} -> {t.exit_price:>12.4f}  qty {t.qty:<12.6f} "
                  f"pnl {t.pnl:+10.2f}  ({t.exit_reason})")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"summary": result.summary(),
                       "equity": [[p.timestamp, p.equity] for p in result.equity_curve]}, fh)
    return 0


def cmd_fetch(args) -> int:
    from .data import CcxtFeed

    cfg = load_config(args.config)
    feed = CcxtFeed(cfg.exchange, args.symbol or cfg.symbol, args.timeframe or cfg.timeframe)
    candles = feed.fetch_closed(limit=args.limit)
    save_csv(candles, args.out)
    print(f"Saved {len(candles)} candles to {args.out}")
    return 0


def cmd_run(args, live: bool) -> int:
    from .broker import CcxtBroker, PaperBroker
    from .data import CcxtFeed
    from .engine import TradingEngine
    from .live import Journal, run_loop
    from .risk import RiskManager

    cfg = load_config(args.config)
    strategy = build_strategy(cfg.strategy, cfg.strategy_params)
    feed = CcxtFeed(cfg.exchange, cfg.symbol, cfg.timeframe)
    if live:
        if not args.i_accept_the_risk:
            print("Live trading places real orders. Re-run with --i-accept-the-risk to continue.", file=sys.stderr)
            return 2
        broker = CcxtBroker(cfg.exchange, cfg.symbol, sandbox=cfg.sandbox)
        logging.warning("LIVE trading %s on %s (sandbox=%s)", cfg.symbol, cfg.exchange, cfg.sandbox)
    else:
        broker = PaperBroker(cfg.symbol, cfg.starting_cash, cfg.fee_rate, cfg.slippage_bps)
    engine = TradingEngine(strategy, broker, RiskManager(cfg.risk))
    run_loop(engine, feed, broker, cfg.poll_seconds, Journal(cfg.journal))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trading_bot", description="Backtest, paper trade or live trade a strategy.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="run a strategy on historical or synthetic data")
    bt.add_argument("--config", help="TOML config file")
    src = bt.add_mutually_exclusive_group()
    src.add_argument("--csv", help="OHLCV CSV file")
    src.add_argument("--synthetic", type=int, default=3000, help="number of synthetic candles (default 3000)")
    bt.add_argument("--seed", type=int, default=42)
    bt.add_argument("--strategy", choices=sorted(STRATEGIES))
    bt.add_argument("--param", action="append", default=[], help="strategy parameter, e.g. fast=10")
    bt.add_argument("--trades", action="store_true", help="list every trade")
    bt.add_argument("--json", help="write summary and equity curve to this file")
    bt.set_defaults(func=cmd_backtest)

    fe = sub.add_parser("fetch", help="download candles from an exchange to CSV (needs ccxt)")
    fe.add_argument("--config")
    fe.add_argument("--symbol")
    fe.add_argument("--timeframe")
    fe.add_argument("--limit", type=int, default=1000)
    fe.add_argument("--out", required=True)
    fe.set_defaults(func=cmd_fetch)

    pa = sub.add_parser("paper", help="simulated trading on live exchange data (needs ccxt)")
    pa.add_argument("--config", required=True)
    pa.set_defaults(func=lambda a: cmd_run(a, live=False))

    lv = sub.add_parser("live", help="REAL orders on an exchange (needs ccxt + API keys)")
    lv.add_argument("--config", required=True)
    lv.add_argument("--i-accept-the-risk", action="store_true", help="required to place real orders")
    lv.set_defaults(func=lambda a: cmd_run(a, live=True))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else (logging.INFO if args.command in ("paper", "live") else logging.WARNING),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return args.func(args)
