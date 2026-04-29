import json
import logging
import pandas as pd
from groq import Groq
from dataclasses import dataclass
from bot.strategy import compute_indicators, Signal
from config import GROQ_API_KEY, GROQ_MODEL, AI_CONFIDENCE_THRESHOLD, TIMEFRAME

log = logging.getLogger(__name__)

CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

SYSTEM_PROMPT = """You are an expert quantitative crypto trader with deep knowledge of technical analysis.
You analyze market data and make precise trading decisions.
You must respond ONLY with a valid JSON object, no extra text."""

_USER_TEMPLATE = """Analyze the following market data for {symbol} on the {timeframe} timeframe and decide whether to BUY, SELL, or HOLD.

## Current Indicators
- Price:      {price:.4f} USDT
- EMA{ema_fast}:     {ema_fast_val:.4f}  (fast)
- EMA{ema_slow}:     {ema_slow_val:.4f}  (slow)
- EMA trend:  {ema_trend}
- RSI({rsi_period}):   {rsi:.2f}  ({rsi_state})
- Volume:     {volume:.2f} (last candle)

## Last 10 Candles (oldest → newest)
```
{candles_table}
```

## Your Task
Based on the data above, provide your trading decision.

Rules:
- BUY only when there is a clear bullish signal with good risk/reward
- SELL only when there is a clear bearish reversal or exit signal
- HOLD when the signal is weak or the market is uncertain
- Never trade against a strong trend

Respond ONLY with this JSON (no markdown, no extra text):
{{"decision": "BUY|SELL|HOLD", "confidence": "LOW|MEDIUM|HIGH", "reasoning": "one concise sentence"}}"""


@dataclass
class AISignal:
    signal: Signal
    confidence: str
    reasoning: str

    def __str__(self) -> str:
        return f"AI={self.signal.value} | Confidence={self.confidence} | {self.reasoning}"


def _build_prompt(df: pd.DataFrame, symbol: str) -> str:
    df = compute_indicators(df)
    df = df.dropna()
    last = df.iloc[-1]

    ema_fast_val = last["ema_fast"]
    ema_slow_val = last["ema_slow"]
    rsi = last["rsi"]

    ema_trend = "BULLISH" if ema_fast_val > ema_slow_val else "BEARISH"
    rsi_state = "overbought" if rsi > 70 else ("oversold" if rsi < 30 else "neutral")

    candles = df.tail(10)[["open", "high", "low", "close", "volume"]].copy()
    candles.index = candles.index.strftime("%H:%M")
    candles_table = candles.to_string(float_format=lambda x: f"{x:.4f}")

    from config import EMA_FAST, EMA_SLOW, RSI_PERIOD
    return _USER_TEMPLATE.format(
        symbol=symbol,
        timeframe=TIMEFRAME,
        price=last["close"],
        ema_fast=EMA_FAST,
        ema_fast_val=ema_fast_val,
        ema_slow=EMA_SLOW,
        ema_slow_val=ema_slow_val,
        ema_trend=ema_trend,
        rsi_period=RSI_PERIOD,
        rsi=rsi,
        rsi_state=rsi_state,
        volume=last["volume"],
        candles_table=candles_table,
    )


def _parse_response(content: str) -> AISignal:
    content = content.strip()
    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    data = json.loads(content.strip())

    raw_decision = data.get("decision", "HOLD").upper()
    signal = Signal[raw_decision] if raw_decision in Signal.__members__ else Signal.HOLD
    confidence = data.get("confidence", "LOW").upper()
    reasoning = data.get("reasoning", "")
    return AISignal(signal, confidence, reasoning)


def analyse(df: pd.DataFrame, symbol: str) -> AISignal:
    client = Groq(api_key=GROQ_API_KEY)
    prompt = _build_prompt(df, symbol)

    log.debug("Sending market data for %s to Groq (%s)...", symbol, GROQ_MODEL)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,   # low temp = more deterministic decisions
        max_tokens=150,
    )

    content = response.choices[0].message.content
    log.debug("Groq raw response: %s", content)

    ai_signal = _parse_response(content)
    log.info("[GROQ %s] %s", symbol, ai_signal)
    return ai_signal


def is_actionable(ai_signal: AISignal) -> bool:
    """Returns True if AI confidence meets or exceeds the configured threshold."""
    return CONFIDENCE_RANK.get(ai_signal.confidence, 0) >= CONFIDENCE_RANK.get(AI_CONFIDENCE_THRESHOLD, 1)
