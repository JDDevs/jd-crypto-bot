import json
import logging
import pandas as pd
import httpx
from groq import Groq, RateLimitError as GroqRateLimitError
from dataclasses import dataclass
from bot.strategy import compute_indicators, Signal
from config import (
    GROQ_API_KEY, GROQ_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL,
    AI_CONFIDENCE_THRESHOLD, TIMEFRAME,
)

log = logging.getLogger(__name__)

CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

SYSTEM_PROMPT = """You are an expert quantitative crypto trader with deep knowledge of technical analysis.
You analyze market data and make precise trading decisions, learning from your past trades.
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
{memory_section}
## Your Task
Based on the data above (and your past experience if shown), provide your trading decision.

Rules:
- BUY only when there is a clear bullish signal with good risk/reward
- SELL only when there is a clear bearish reversal or exit signal
- HOLD when the signal is weak or the market is uncertain
- Never trade against a strong trend
- Apply the lessons you've learned from past trades when relevant

Respond ONLY with this JSON (no markdown, no extra text):
{{"decision": "BUY|SELL|HOLD", "confidence": "LOW|MEDIUM|HIGH", "reasoning": "one concise sentence"}}"""


REFLECTION_PROMPT = """You previously analyzed {symbol} and decided to BUY at {entry_price:.4f}.

Your reasoning at the time was:
"{entry_reasoning}"

The trade closed at {exit_price:.4f} with PnL={pnl:+.4f} USDT (reason: {exit_reason}).

In ONE concise sentence (max 25 words), what's a specific, actionable lesson for similar setups
in the future? Focus on what to look for or avoid based on this outcome.

Respond ONLY with this JSON (no markdown, no extra text):
{{"lesson": "..."}}"""


@dataclass
class AISignal:
    signal: Signal
    confidence: str
    reasoning: str

    def __str__(self) -> str:
        return f"AI={self.signal.value} | Confidence={self.confidence} | {self.reasoning}"


# ---------------------------------------------------------------------------
# Memory-aware prompt building
# ---------------------------------------------------------------------------

def _build_memory_section(pair_state: dict | None) -> str:
    """Returns extra prompt sections with the AI's track record + lessons."""
    if not pair_state:
        return ""

    parts: list[str] = []

    stats = pair_state.get("stats", {})
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    pnl = stats.get("total_pnl", 0.0)
    total = wins + losses
    if total > 0:
        win_rate = (wins / total) * 100
        parts.append(
            f"\n## Your Track Record on This Pair\n"
            f"- {total} trades closed | Win rate: {win_rate:.0f}% ({wins}W/{losses}L)\n"
            f"- Cumulative PnL: {pnl:+.4f} USDT"
        )

    closed = pair_state.get("closed_trades", [])
    if closed:
        last_n = closed[-5:]
        lines = []
        for t in reversed(last_n):
            lines.append(
                f"- BUY @ {t['entry_price']:.4f} → SELL @ {t['exit_price']:.4f} "
                f"({t['pnl']:+.4f} USDT, {t['exit_reason']}) — entry rationale: \"{t['entry_reasoning']}\""
            )
        parts.append("\n## Last Closed Trades (most recent first)\n" + "\n".join(lines))

    lessons = pair_state.get("lessons_learned", [])
    if lessons:
        last_lessons = lessons[-8:]
        lines = [f"- {l['lesson']}" for l in last_lessons]
        parts.append("\n## Lessons You've Learned (apply when relevant)\n" + "\n".join(lines))

    return "\n".join(parts) + ("\n" if parts else "")


def _build_prompt(df: pd.DataFrame, symbol: str, pair_state: dict | None = None) -> str:
    df = compute_indicators(df).dropna()
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
        memory_section=_build_memory_section(pair_state),
    )


def _parse_response(content: str) -> AISignal:
    content = content.strip()
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


# ---------------------------------------------------------------------------
# LLM provider calls (Groq primary, Gemini fallback)
# ---------------------------------------------------------------------------

def _call_groq(prompt: str, max_tokens: int = 150) -> str:
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def _call_gemini(prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 150},
    }
    resp = httpx.post(url, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_llm(prompt: str, max_tokens: int = 150) -> tuple[str, str]:
    """Returns (content, provider_name). Tries Groq first, falls back to Gemini."""
    if GROQ_API_KEY:
        try:
            return _call_groq(prompt, max_tokens), "GROQ"
        except GroqRateLimitError:
            log.warning("Groq rate limit hit — switching to Gemini fallback")
        except Exception as e:
            log.warning("Groq error: %s — switching to Gemini fallback", e)

    if GEMINI_API_KEY:
        return _call_gemini(prompt), "GEMINI"

    raise RuntimeError("No AI provider available. Set GROQ_API_KEY or GEMINI_API_KEY in .env")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse(df: pd.DataFrame, symbol: str, pair_state: dict | None = None) -> AISignal:
    prompt = _build_prompt(df, symbol, pair_state)
    content, provider = _call_llm(prompt)
    log.debug("%s raw response: %s", provider, content)
    ai_signal = _parse_response(content)
    log.info("[%s %s] %s", provider, symbol, ai_signal)
    return ai_signal


def reflect(symbol: str, closed_trade: dict) -> str:
    if not closed_trade.get("entry_reasoning"):
        return ""

    prompt = REFLECTION_PROMPT.format(
        symbol=symbol,
        entry_price=closed_trade["entry_price"],
        entry_reasoning=closed_trade["entry_reasoning"],
        exit_price=closed_trade["exit_price"],
        pnl=closed_trade["pnl"],
        exit_reason=closed_trade["exit_reason"],
    )
    try:
        content, provider = _call_llm(prompt, max_tokens=100)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content.strip())
        lesson = data.get("lesson", "").strip()
        log.info("[REFLECT/%s %s] %s", provider, symbol, lesson)
        return lesson
    except Exception as e:
        log.warning("[REFLECT %s] Failed: %s", symbol, e)
        return ""


def is_actionable(ai_signal: AISignal) -> bool:
    return CONFIDENCE_RANK.get(ai_signal.confidence, 0) >= CONFIDENCE_RANK.get(AI_CONFIDENCE_THRESHOLD, 1)
