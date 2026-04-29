"""
Backtest the EMA crossover + RSI strategy using the backtesting.py library.

Usage:
    python backtest.py                      # uses default config values
    python backtest.py --symbol BTC/USDT --timeframe 5m --days 90
"""
import argparse
import ccxt
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from config import (
    EMA_FAST, EMA_SLOW, RSI_PERIOD,
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    TAKE_PROFIT_PCT, STOP_LOSS_PCT,
    SYMBOL, TIMEFRAME,
)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_historical(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    exchange = ccxt.binance({"enableRateLimit": True})
    limit = min(days * 288, 1000)  # 288 x 5m candles = 1 day
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"], unit="ms")
    df.set_index("Date", inplace=True)
    return df


# ---------------------------------------------------------------------------
# Strategy definition
# ---------------------------------------------------------------------------

class EmaCrossRsi(Strategy):
    ema_fast = EMA_FAST
    ema_slow = EMA_SLOW
    rsi_period = RSI_PERIOD
    rsi_oversold = RSI_OVERSOLD
    rsi_overbought = RSI_OVERBOUGHT
    tp_pct = TAKE_PROFIT_PCT
    sl_pct = STOP_LOSS_PCT

    def init(self):
        close = self.data.Close
        self.ema_f = self.I(lambda x: pd.Series(x).ewm(span=self.ema_fast, adjust=False).mean(), close)
        self.ema_s = self.I(lambda x: pd.Series(x).ewm(span=self.ema_slow, adjust=False).mean(), close)

        def _rsi(x):
            s = pd.Series(x)
            delta = s.diff()
            gain = delta.clip(lower=0).ewm(com=self.rsi_period - 1, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(com=self.rsi_period - 1, adjust=False).mean()
            rs = gain / loss.replace(0, float("inf"))
            return 100 - (100 / (1 + rs))

        self.rsi = self.I(_rsi, close)

    def next(self):
        price = self.data.Close[-1]

        # Entry: EMA bullish cross + RSI not overbought
        if crossover(self.ema_f, self.ema_s) and self.rsi[-1] < self.rsi_overbought:
            if not self.position:
                sl = price * (1 - self.sl_pct)
                tp = price * (1 + self.tp_pct)
                self.buy(sl=sl, tp=tp)

        # Exit: EMA bearish cross + RSI not oversold
        elif crossover(self.ema_s, self.ema_f) and self.rsi[-1] > self.rsi_oversold:
            if self.position.is_long:
                self.position.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backtest EMA+RSI strategy")
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--timeframe", default=TIMEFRAME)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--cash", type=float, default=1000.0)
    parser.add_argument("--commission", type=float, default=0.001)  # 0.1% Binance
    args = parser.parse_args()

    print(f"Fetching {args.days} days of {args.symbol} {args.timeframe} data...")
    df = fetch_historical(args.symbol, args.timeframe, args.days)
    print(f"  {len(df)} candles loaded from {df.index[0]} to {df.index[-1]}")

    bt = Backtest(
        df,
        EmaCrossRsi,
        cash=args.cash,
        commission=args.commission,
        exclusive_orders=True,
    )
    stats = bt.run()
    print("\n--- Backtest Results ---")
    print(stats)
    bt.plot()


if __name__ == "__main__":
    main()
