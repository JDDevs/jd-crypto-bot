import pandas as pd
import pandas_ta as ta
from dataclasses import dataclass
from enum import Enum
from config import EMA_FAST, EMA_SLOW, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal: Signal
    ema_fast: float
    ema_slow: float
    rsi: float
    close: float

    def __str__(self) -> str:
        return (
            f"Signal={self.signal.value} | "
            f"EMA{EMA_FAST}={self.ema_fast:.4f} EMA{EMA_SLOW}={self.ema_slow:.4f} | "
            f"RSI={self.rsi:.2f} | Close={self.close:.4f}"
        )


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[f"ema_fast"] = ta.ema(df["close"], length=EMA_FAST)
    df[f"ema_slow"] = ta.ema(df["close"], length=EMA_SLOW)
    df["rsi"] = ta.rsi(df["close"], length=RSI_PERIOD)
    return df


def evaluate(df: pd.DataFrame) -> StrategyResult:
    """Evaluate the last two candles to detect an EMA crossover with RSI filter."""
    df = compute_indicators(df)
    df.dropna(inplace=True)

    if len(df) < 2:
        return StrategyResult(Signal.HOLD, 0, 0, 50, 0)

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    ema_fast_now = curr["ema_fast"]
    ema_slow_now = curr["ema_slow"]
    ema_fast_prev = prev["ema_fast"]
    ema_slow_prev = prev["ema_slow"]
    rsi = curr["rsi"]
    close = curr["close"]

    # Bullish crossover: fast crosses above slow, RSI not overbought
    if ema_fast_prev < ema_slow_prev and ema_fast_now > ema_slow_now and rsi < RSI_OVERBOUGHT:
        signal = Signal.BUY

    # Bearish crossover: fast crosses below slow, RSI not oversold
    elif ema_fast_prev > ema_slow_prev and ema_fast_now < ema_slow_now and rsi > RSI_OVERSOLD:
        signal = Signal.SELL

    else:
        signal = Signal.HOLD

    return StrategyResult(signal, ema_fast_now, ema_slow_now, rsi, close)
