import json
import re
import ast
import time
import threading
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
    RE_ENTRY_AI_WINDOW,
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

    # Layer B: recent-exit warning — inject if closed within RE_ENTRY_AI_WINDOW seconds
    if closed:
        last_trade = closed[-1]
        closed_at = last_trade.get("closed_at", "")
        if closed_at:
            try:
                from datetime import datetime, timezone
                closed_time = datetime.fromisoformat(closed_at)
                elapsed_s = (datetime.now(timezone.utc) - closed_time).total_seconds()
                if 0 < elapsed_s < RE_ENTRY_AI_WINDOW:
                    mins = int(elapsed_s / 60)
                    exit_p = last_trade.get("exit_price", 0)
                    exit_pnl = last_trade.get("pnl", 0)
                    exit_reason = last_trade.get("exit_reason", "")
                    parts.append(
                        f"\n## ⚠️ RECENT EXIT — {mins} min ago\n"
                        f"- You closed this pair {mins} min ago at {exit_p:.4f} USDT "
                        f"(PnL: {exit_pnl:+.4f}, reason: {exit_reason})\n"
                        f"- DO NOT re-enter if price is still near or above your exit price.\n"
                        f"- Only consider BUY if price has pulled back significantly "
                        f"or a clearly new setup has formed."
                    )
            except Exception:
                pass

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

    # Strip markdown code fences
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    data: dict = {}
    # 1st attempt: standard JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # 2nd attempt: extract first {...} block and parse
        m = re.search(r"\{[^{}]+\}", content, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                # 3rd attempt: ast.literal_eval handles single-quoted dicts
                try:
                    data = ast.literal_eval(m.group())
                except Exception:
                    pass
        if not data:
            log.warning("Could not parse AI response: %s", content[:120])
            return AISignal(Signal.HOLD, "LOW", "unparseable response")

    raw_decision = data.get("decision", "HOLD").upper()
    signal = Signal[raw_decision] if raw_decision in Signal.__members__ else Signal.HOLD
    confidence = data.get("confidence", "LOW").upper()
    reasoning = data.get("reasoning", "")
    return AISignal(signal, confidence, reasoning)


# ---------------------------------------------------------------------------
# LLM provider calls (Groq primary, Gemini fallback)
# ---------------------------------------------------------------------------

# Gemini rate limiter — free tier is 15 RPM = 1 call every 4 seconds
_gemini_lock = threading.Lock()
_gemini_last_call: float = 0.0
_GEMINI_MIN_INTERVAL = 4.1  # slightly over 4s to stay safely under 15 RPM


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
    global _gemini_last_call
    with _gemini_lock:
        wait = _GEMINI_MIN_INTERVAL - (time.time() - _gemini_last_call)
        if wait > 0:
            time.sleep(wait)
        _gemini_last_call = time.time()

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
    """Returns (content, provider_name). Tries Gemini first, falls back to Groq."""
    if GEMINI_API_KEY:
        try:
            return _call_gemini(prompt), "GEMINI"
        except httpx.HTTPStatusError as e:
            log.warning("Gemini HTTP %s — switching to Groq fallback", e.response.status_code)
        except Exception as e:
            log.warning("Gemini error: %s — switching to Groq fallback", e)

    if GROQ_API_KEY:
        try:
            return _call_groq(prompt, max_tokens), "GROQ"
        except GroqRateLimitError:
            log.warning("Groq rate limit hit — no fallback available")
        except Exception as e:
            log.warning("Groq error: %s", e)

    raise RuntimeError("No AI provider available. Set GEMINI_API_KEY or GROQ_API_KEY in .env")


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
        content = content.strip()

        data: dict = {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]+\}", content, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group())
                except json.JSONDecodeError:
                    data = ast.literal_eval(m.group())

        lesson = data.get("lesson", "").strip()
        log.info("[REFLECT/%s %s] %s", provider, symbol, lesson)
        return lesson
    except Exception as e:
        log.warning("[REFLECT %s] Failed: %s", symbol, e)
        return ""


def is_actionable(ai_signal: AISignal, threshold: str | None = None) -> bool:
    t = threshold if threshold else AI_CONFIDENCE_THRESHOLD
    return CONFIDENCE_RANK.get(ai_signal.confidence, 0) >= CONFIDENCE_RANK.get(t, 1)


# ---------------------------------------------------------------------------
# Macro sentiment — overall market outlook (called once per hour)
# ---------------------------------------------------------------------------

_MACRO_PROMPT = """You are analyzing the overall crypto market environment for scalp trading.

## Multi-pair overview (latest AI signals)
{symbol_lines}

## Fear & Greed Index: {fg_value} ({fg_label})

Is the current market FAVORABLE, NEUTRAL, or UNFAVORABLE for opening new LONG (BUY) positions?

Rules:
- FAVORABLE: majority of pairs bullish, healthy Fear&Greed (25-75)
- UNFAVORABLE: majority bearish, extreme fear (<20) or extreme greed (>80), no clear direction
- NEUTRAL: mixed signals — proceed with caution

Respond ONLY with this JSON (no markdown):
{{"outlook": "FAVORABLE|NEUTRAL|UNFAVORABLE", "reasoning": "one concise sentence"}}"""


def macro_analysis(symbol_data: dict, fear_greed: int) -> tuple[str, str]:
    """Returns (outlook, reasoning). outlook is FAVORABLE | NEUTRAL | UNFAVORABLE."""
    fg_label = (
        "Extreme Fear" if fear_greed < 25 else
        "Fear"         if fear_greed < 45 else
        "Neutral"      if fear_greed < 55 else
        "Greed"        if fear_greed < 75 else "Extreme Greed"
    )
    lines = [
        f"- {sym}: signal={d['last_signal']} ({d['last_confidence']}) price={d['last_price']:.4f}"
        for sym, d in symbol_data.items()
    ]
    prompt = _MACRO_PROMPT.format(
        symbol_lines="\n".join(lines),
        fg_value=fear_greed,
        fg_label=fg_label,
    )
    try:
        content, provider = _call_llm(prompt, max_tokens=80)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        data: dict = {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]+\}", content, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group())
                except json.JSONDecodeError:
                    data = ast.literal_eval(m.group())

        outlook = data.get("outlook", "NEUTRAL").upper()
        if outlook not in ("FAVORABLE", "NEUTRAL", "UNFAVORABLE"):
            outlook = "NEUTRAL"
        reasoning = data.get("reasoning", "")
        log.info("[MACRO/%s] %s — %s", provider, outlook, reasoning)
        return outlook, reasoning
    except Exception as e:
        log.warning("[MACRO] Failed: %s", e)
        return "NEUTRAL", ""
