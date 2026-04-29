import ccxt
import pandas as pd
import logging
from config import (
    API_KEY, API_SECRET, EXCHANGE_ID, TESTNET,
    SYMBOL, TIMEFRAME, CANDLE_LIMIT,
)

log = logging.getLogger(__name__)


def build_exchange() -> ccxt.Exchange:
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    exchange = exchange_class({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if TESTNET:
        exchange.set_sandbox_mode(True)
        log.info("Running in TESTNET mode")
    return exchange


def fetch_candles(exchange: ccxt.Exchange, symbol: str = SYMBOL,
                  timeframe: str = TIMEFRAME, limit: int = CANDLE_LIMIT) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df


def fetch_balance(exchange: ccxt.Exchange, currency: str = "USDT") -> float:
    balance = exchange.fetch_balance()
    return float(balance["free"].get(currency, 0.0))


def fetch_ticker(exchange: ccxt.Exchange, symbol: str = SYMBOL) -> dict:
    return exchange.fetch_ticker(symbol)


def place_market_order(exchange: ccxt.Exchange, symbol: str,
                       side: str, amount: float) -> dict:
    log.info("Placing %s market order: %.6f %s", side.upper(), amount, symbol)
    return exchange.create_market_order(symbol, side, amount)


def place_limit_order(exchange: ccxt.Exchange, symbol: str,
                      side: str, amount: float, price: float) -> dict:
    log.info("Placing %s limit order: %.6f %s @ %.4f", side.upper(), amount, symbol, price)
    return exchange.create_limit_order(symbol, side, amount, price)
