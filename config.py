import os
from dotenv import load_dotenv

load_dotenv()

# Exchange
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")
TESTNET = os.getenv("TESTNET", "true").lower() == "true"

# Trading pairs (comma-separated for multi-pair) and timeframe
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", os.getenv("SYMBOL", "BTC/USDT")).split(",") if s.strip()]
SYMBOL = SYMBOLS[0]  # Backwards-compat single symbol used by backtest.py
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

# Groq AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
AI_CONFIDENCE_THRESHOLD = os.getenv("AI_CONFIDENCE_THRESHOLD", "MEDIUM")  # LOW | MEDIUM | HIGH

# Web dashboard
DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))

# Telegram notifications
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
