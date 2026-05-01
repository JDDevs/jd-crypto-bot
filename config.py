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
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "2"))        # max simultaneous positions

# Trailing stop — locks in profit as price moves up
TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
TRAILING_ACTIVATE_PCT = float(os.getenv("TRAILING_ACTIVATE_PCT", "0.003"))  # arms after +0.3%
TRAILING_DISTANCE_PCT = float(os.getenv("TRAILING_DISTANCE_PCT", "0.002"))  # trails 0.2% behind peak

# Candles to fetch
CANDLE_LIMIT = int(os.getenv("CANDLE_LIMIT", "100"))

# Loop interval (seconds) — should match the timeframe approximately
LOOP_SLEEP = int(os.getenv("LOOP_SLEEP", "30"))

# Groq AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
AI_CONFIDENCE_THRESHOLD = os.getenv("AI_CONFIDENCE_THRESHOLD", "LOW")  # LOW | MEDIUM | HIGH

# Active AI monitoring while in an open position
AI_HOLD_CHECK_INTERVAL = int(os.getenv("AI_HOLD_CHECK_INTERVAL", "300"))   # seconds between checks
AI_HOLD_PRICE_MOVE = float(os.getenv("AI_HOLD_PRICE_MOVE", "0.003"))       # also trigger on 0.3% move

# Re-entry protection — prevents FOMO re-buys near the last exit price
RE_ENTRY_COOLDOWN = int(os.getenv("RE_ENTRY_COOLDOWN", "300"))              # 5-min hard cooldown
RE_ENTRY_PRICE_BUFFER = float(os.getenv("RE_ENTRY_PRICE_BUFFER", "0.003")) # block if price > exit +0.3%
RE_ENTRY_AI_WINDOW = int(os.getenv("RE_ENTRY_AI_WINDOW", "1800"))          # inject warning for 30 min

# Volume filter — only enter when last candle volume confirms the move
VOLUME_FILTER_ENABLED = os.getenv("VOLUME_FILTER_ENABLED", "true").lower() == "true"
VOLUME_FILTER_PERIODS = int(os.getenv("VOLUME_FILTER_PERIODS", "20"))      # compare vs avg of last N candles
VOLUME_FILTER_MULT    = float(os.getenv("VOLUME_FILTER_MULT", "1.0"))      # vol >= avg * mult to pass

# VWAP filter — only take BUY signals when price is above session VWAP
VWAP_FILTER_ENABLED = os.getenv("VWAP_FILTER_ENABLED", "true").lower() == "true"

# Trading hours blackout (UTC) — avoid thin-liquidity windows
TRADING_BLACKOUT_ENABLED = os.getenv("TRADING_BLACKOUT_ENABLED", "true").lower() == "true"
BLACKOUT_START = int(os.getenv("BLACKOUT_START", "23"))   # 23:00 UTC
BLACKOUT_END   = int(os.getenv("BLACKOUT_END", "2"))      # 02:00 UTC (wraps midnight)

# Fear & Greed index (alternative.me — free, no key needed)
FEAR_GREED_ENABLED = os.getenv("FEAR_GREED_ENABLED", "true").lower() == "true"
FEAR_GREED_MIN     = int(os.getenv("FEAR_GREED_MIN", "20"))    # block BUY in Extreme Fear
FEAR_GREED_MAX     = int(os.getenv("FEAR_GREED_MAX", "80"))    # block BUY in Extreme Greed
FEAR_GREED_TTL     = int(os.getenv("FEAR_GREED_TTL", "300"))   # re-fetch every 5 min

# Slippage warning — logs if fill price diverges too much from signal price
SLIPPAGE_WARN_PCT = float(os.getenv("SLIPPAGE_WARN_PCT", "0.001"))  # warn if >0.1%

# Macro sentiment check — AI overview of all pairs once per hour
MACRO_CHECK_INTERVAL = int(os.getenv("MACRO_CHECK_INTERVAL", "3600"))  # seconds

# Google Gemini (fallback when Groq is rate-limited)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Web dashboard
DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))

# Telegram notifications
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
