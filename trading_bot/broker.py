"""Order execution: a simulated paper broker and a live ccxt-backed broker."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Fill:
    side: str  # "buy" or "sell"
    qty: float
    price: float
    fee: float
    timestamp: int


class Broker:
    """Long-only spot broker interface for a single symbol."""

    symbol: str

    def cash(self) -> float:
        raise NotImplementedError

    def position(self) -> float:
        raise NotImplementedError

    def buy(self, qty: float, ref_price: float, timestamp: int) -> Fill | None:
        raise NotImplementedError

    def sell(self, qty: float, ref_price: float, timestamp: int) -> Fill | None:
        raise NotImplementedError

    def equity(self, price: float) -> float:
        return self.cash() + self.position() * price


class PaperBroker(Broker):
    """Simulated fills with proportional fees and slippage."""

    def __init__(self, symbol: str, starting_cash: float = 10_000.0, fee_rate: float = 0.001, slippage_bps: float = 5.0):
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.symbol = symbol
        self._cash = float(starting_cash)
        self._pos = 0.0
        self.fee_rate = fee_rate
        self.slippage = slippage_bps / 10_000

    def cash(self) -> float:
        return self._cash

    def position(self) -> float:
        return self._pos

    def buy(self, qty, ref_price, timestamp):
        price = ref_price * (1 + self.slippage)
        max_qty = self._cash / (price * (1 + self.fee_rate))
        qty = min(qty, max_qty)
        if qty <= 0:
            return None
        notional = qty * price
        fee = notional * self.fee_rate
        self._cash -= notional + fee
        self._pos += qty
        return Fill("buy", qty, price, fee, timestamp)

    def sell(self, qty, ref_price, timestamp):
        qty = min(qty, self._pos)
        if qty <= 0:
            return None
        price = ref_price * (1 - self.slippage)
        notional = qty * price
        fee = notional * self.fee_rate
        self._cash += notional - fee
        self._pos -= qty
        if self._pos < 1e-12:
            self._pos = 0.0
        return Fill("sell", qty, price, fee, timestamp)


class CcxtBroker(Broker):
    """Places real market orders through ccxt. Real money is at risk.

    API credentials are read from the environment variables
    ``EXCHANGE_API_KEY`` and ``EXCHANGE_API_SECRET`` (and optionally
    ``EXCHANGE_API_PASSWORD``), never from config files.
    """

    def __init__(self, exchange_id: str, symbol: str, sandbox: bool = True, exchange=None):
        if exchange is None:
            try:
                import ccxt  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError("ccxt is required for live trading: pip install ccxt") from exc
            key, secret = os.environ.get("EXCHANGE_API_KEY"), os.environ.get("EXCHANGE_API_SECRET")
            if not key or not secret:
                raise RuntimeError("Set EXCHANGE_API_KEY and EXCHANGE_API_SECRET to trade live")
            params = {"apiKey": key, "secret": secret, "enableRateLimit": True}
            if os.environ.get("EXCHANGE_API_PASSWORD"):
                params["password"] = os.environ["EXCHANGE_API_PASSWORD"]
            exchange = getattr(ccxt, exchange_id)(params)
            if sandbox:
                exchange.set_sandbox_mode(True)
            exchange.load_markets()
        self.exchange = exchange
        self.symbol = symbol
        self.base, self.quote = symbol.split("/")[0], symbol.split("/")[1].split(":")[0]

    def _balance(self, asset: str) -> float:
        bal = self.exchange.fetch_balance()
        return float(bal.get("free", {}).get(asset) or 0.0)

    def cash(self) -> float:
        return self._balance(self.quote)

    def position(self) -> float:
        return self._balance(self.base)

    def _order(self, side: str, qty: float, ref_price: float, timestamp: int) -> Fill | None:
        amount = float(self.exchange.amount_to_precision(self.symbol, qty))
        if amount <= 0:
            log.warning("Order amount %s rounds to zero; skipping", qty)
            return None
        log.info("LIVE %s %s %s", side.upper(), amount, self.symbol)
        order = self.exchange.create_order(self.symbol, "market", side, amount)
        price = float(order.get("average") or order.get("price") or ref_price)
        filled = float(order.get("filled") or amount)
        fee = float((order.get("fee") or {}).get("cost") or 0.0)
        return Fill(side, filled, price, fee, timestamp)

    def buy(self, qty, ref_price, timestamp):
        return self._order("buy", qty, ref_price, timestamp)

    def sell(self, qty, ref_price, timestamp):
        return self._order("sell", min(qty, self.position()), ref_price, timestamp)
