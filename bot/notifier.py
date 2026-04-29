"""
Telegram notification module.

Sends messages via Telegram Bot API using simple HTTP calls.
All functions are fire-and-forget — failures are logged and swallowed
so a Telegram outage never stops the trader.
"""
import logging
import httpx
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED

log = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str) -> None:
    if not TELEGRAM_ENABLED:
        return
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env")
        return
    try:
        url = _BASE.format(token=TELEGRAM_TOKEN)
        httpx.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def notify_buy(symbol: str, entry: float, tp: float, sl: float,
               quantity: float, reasoning: str) -> None:
    tp_pct = (tp / entry - 1) * 100
    sl_pct = (1 - sl / entry) * 100
    _send(
        f"🟢 *BUY* — {symbol}\n"
        f"Entry:  `{entry:,.4f}` USDT\n"
        f"TP:     `{tp:,.4f}` *(+{tp_pct:.2f}%)*\n"
        f"SL:     `{sl:,.4f}` *(-{sl_pct:.2f}%)*\n"
        f"Qty:    `{quantity:.6f}`\n"
        f"📝 _{reasoning}_"
    )


def notify_close(symbol: str, entry: float, exit_price: float,
                 pnl: float, reason: str, total_pnl: float) -> None:
    emoji = "✅" if pnl >= 0 else "❌"
    pnl_sign = "+" if pnl >= 0 else ""
    total_sign = "+" if total_pnl >= 0 else ""
    _send(
        f"{emoji} *CLOSED* — {symbol}\n"
        f"Reason: `{reason}`\n"
        f"Entry:  `{entry:,.4f}` → Exit: `{exit_price:,.4f}`\n"
        f"PnL:    `{pnl_sign}{pnl:.4f}` USDT\n"
        f"Total PnL: `{total_sign}{total_pnl:.4f}` USDT"
    )


def notify_lesson(symbol: str, lesson: str) -> None:
    _send(f"💡 *Lesson* — {symbol}\n_{lesson}_")


def notify_error(symbol: str, error: str) -> None:
    _send(f"⚠️ *Error* — {symbol}\n`{error}`")
