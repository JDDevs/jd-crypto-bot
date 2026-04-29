import os
from dotenv import load_dotenv

load_dotenv()

# Exchange
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")
TESTNET = os.getenv("TESTNET", "true").lower() == "true"

# Trading pair and timeframe
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")  # 1m, 5m, 15m, 1h

# Strategy parameters (EMA crossover + RSI filter)
EMA_FAST = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW = int(os.getenv("EMA_SLOW", "21"))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "40"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "70"))

# Risk management
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))   # 1% of balance per trade
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.006"))  # 0.6%
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.003"))     # 0.3%
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "1"))

# Candles to fetch
CANDLE_LIMIT = int(os.getenv("CANDLE_LIMIT", "100"))

# Loop interval (seconds) — should match the timeframe approximately
LOOP_SLEEP = int(os.getenv("LOOP_SLEEP", "30"))
