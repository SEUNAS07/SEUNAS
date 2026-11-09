"""Load bot configuration from a TOML file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .risk import RiskConfig


@dataclass
class BotConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    exchange: str = "binance"
    sandbox: bool = True
    poll_seconds: int = 30
    strategy: str = "sma_crossover"
    strategy_params: dict = field(default_factory=dict)
    starting_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    journal: str = "trades.csv"
    risk: RiskConfig = field(default_factory=RiskConfig)


def load_config(path: str | Path | None) -> BotConfig:
    cfg = BotConfig()
    if path is None:
        return cfg
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    bot = raw.get("bot", {})
    for key in ("symbol", "timeframe", "exchange", "sandbox", "poll_seconds", "journal"):
        if key in bot:
            setattr(cfg, key, bot[key])

    strat = raw.get("strategy", {})
    cfg.strategy = strat.get("name", cfg.strategy)
    cfg.strategy_params = dict(strat.get("params", {}))

    paper = raw.get("paper", {})
    for key in ("starting_cash", "fee_rate", "slippage_bps"):
        if key in paper:
            setattr(cfg, key, float(paper[key]))

    risk_raw = raw.get("risk", {})
    known = {f.name for f in fields(RiskConfig)}
    unknown = set(risk_raw) - known
    if unknown:
        raise ValueError(f"Unknown [risk] settings: {sorted(unknown)}")
    cfg.risk = RiskConfig(**risk_raw)
    cfg.risk.validate()
    return cfg
