import pandas as pd
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
    trigger: str = ""

    def __str__(self) -> str:
        return (
            f"Signal={self.signal.value} | "
            f"EMA{EMA_FAST}={self.ema_fast:.4f} EMA{EMA_SLOW}={self.ema_slow:.4f} | "
            f"RSI={self.rsi:.2f} | Close={self.close:.4f}"
        )


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["rsi"] = _rsi(df["close"], RSI_PERIOD)
    return df


def evaluate(df: pd.DataFrame) -> StrategyResult:
    df = compute_indicators(df).dropna()

    if len(df) < 2:
        return StrategyResult(Signal.HOLD, 0, 0, 50, 0)

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    ema_fast_now  = curr["ema_fast"]
    ema_slow_now  = curr["ema_slow"]
    ema_fast_prev = prev["ema_fast"]
    ema_slow_prev = prev["ema_slow"]
    rsi_now  = curr["rsi"]
    rsi_prev = prev["rsi"]
    close    = curr["close"]

    # --- BUY conditions (any one is enough to trigger an AI consultation) ---
    ema_bullish_cross = (ema_fast_prev < ema_slow_prev and ema_fast_now > ema_slow_now)
    rsi_recovery      = (rsi_prev <= RSI_OVERSOLD and rsi_now > RSI_OVERSOLD)  # RSI climbing out of oversold
    trend_entry       = (ema_fast_now > ema_slow_now and rsi_prev < 45 <= rsi_now)  # RSI crosses 45 in bullish trend

    # --- SELL conditions ---
    ema_bearish_cross = (ema_fast_prev > ema_slow_prev and ema_fast_now < ema_slow_now)
    rsi_exhaustion    = (rsi_prev >= RSI_OVERBOUGHT and rsi_now < RSI_OVERBOUGHT)  # RSI dropping from overbought

    trigger = ""
    if (ema_bullish_cross or rsi_recovery or trend_entry) and rsi_now < RSI_OVERBOUGHT:
        signal = Signal.BUY
        if ema_bullish_cross:
            trigger = f"EMA{EMA_FAST} cruzó sobre EMA{EMA_SLOW} — cruce alcista confirmado"
        elif rsi_recovery:
            trigger = f"RSI saliendo de zona sobrevendida ({rsi_prev:.1f} → {rsi_now:.1f})"
        elif trend_entry:
            trigger = f"RSI tomando impulso en tendencia alcista ({rsi_prev:.1f} → {rsi_now:.1f})"
    elif (ema_bearish_cross or rsi_exhaustion) and rsi_now > RSI_OVERSOLD:
        signal = Signal.SELL
        if ema_bearish_cross:
            trigger = f"EMA{EMA_FAST} cruzó bajo EMA{EMA_SLOW} — cruce bajista confirmado"
        elif rsi_exhaustion:
            trigger = f"RSI bajando desde sobrecompra ({rsi_prev:.1f} → {rsi_now:.1f})"
    else:
        signal = Signal.HOLD

    return StrategyResult(signal, ema_fast_now, ema_slow_now, rsi_now, close, trigger)
