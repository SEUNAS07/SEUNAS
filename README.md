# SEUNAS Trading Bot

A small, dependency-light Python trading bot with three modes:

| Mode | What it does | Needs |
|---|---|---|
| `backtest` | Runs a strategy over a CSV file or synthetic data and prints performance | Python 3.11+ only |
| `paper` | Trades with fake money on live exchange prices | `ccxt` |
| `live` | Places **real orders** on an exchange (testnet by default) | `ccxt` + API keys + `--i-accept-the-risk` |

> **Warning.** This is software, not financial advice. Most simple strategies lose money
> after fees. Backtest, then paper trade for a good while, then use the exchange
> testnet (`sandbox = true`) before you risk anything you can't afford to lose.

## Quick start

```bash
# Backtest on synthetic data (no install needed)
python -m trading_bot backtest --strategy sma_crossover --param fast=10 --param slow=40 --trades

# Backtest on your own data (columns: timestamp/date, open, high, low, close[, volume])
python -m trading_bot backtest --csv data/BTCUSDT-1h.csv --config config.example.toml

# Download real history, then paper trade it live
pip install -r requirements.txt
cp config.example.toml config.toml
python -m trading_bot fetch --config config.toml --limit 1000 --out data/BTCUSDT-1h.csv
python -m trading_bot paper --config config.toml

# Live (testnet while sandbox = true in config.toml)
export EXCHANGE_API_KEY=... EXCHANGE_API_SECRET=...
python -m trading_bot live --config config.toml --i-accept-the-risk
```

Synthetic data is a random walk, so a good result on it tells you only that the code runs.

## How it works

```
candles ──► Strategy ──signal──► RiskManager ──size/stop──► Broker (Paper | ccxt)
   ▲                                                            │
   └──────────────────── TradingEngine ◄──── fills ─────────────┘
```

- **Signals are computed on closed candles only** and filled afterwards (at the next bar's
  open in backtests, at the current price live), so backtests can't trade on information from the future.
- **Fees and slippage** are charged on every simulated fill.
- **Long only, spot only, one symbol** per bot.

### Strategies (`trading_bot/strategies.py`)
- `sma_crossover`: buy when the fast MA crosses above the slow MA, sell on the reverse cross. Params: `fast`, `slow`, `use_ema`.
- `rsi_mean_reversion`: buy when RSI is oversold, sell when it's overbought. You can also require price to be above a long SMA. Params: `period`, `oversold`, `overbought`, `trend_sma`.

To add one, subclass `Strategy`, implement `generate(candles, in_position) -> Signal`, and register it in `STRATEGIES`.

### Risk controls (`[risk]` in the config)
- **Position size**: the stop is set at `atr_stop_mult × ATR`. The position is sized so that hitting the stop loses `risk_per_trade` of equity. It is also capped at `max_position_pct` of equity and by available cash.
- **Stop-loss and optional take-profit** on every trade. If price gaps through a level, the backtest fills at the open, not at the stop price.
- **Daily loss limit**: no new entries after losing `max_daily_loss_pct` in a UTC day.
- **Drawdown kill switch**: flattens the position and stops trading after `max_drawdown_pct` from peak equity.

### Live-mode notes
- API keys are read from environment variables only, never from config files.
- Stops are checked against the ticker price every `poll_seconds`. They are *not* resting
  exchange orders, so the bot must be running to protect a position.
- On start-up, any coins already held are adopted and protected with an ATR stop.
- Closed trades are appended to the `journal` CSV.

## Tests

```bash
python -m unittest discover -s tests -v
```
