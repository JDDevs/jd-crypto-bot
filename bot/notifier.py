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
               quantity: float, reasoning: str,
               confidence: str = "", trigger: str = "") -> None:
    tp_pct = (tp / entry - 1) * 100
    sl_pct = (1 - sl / entry) * 100
    conf_label = {"HIGH": "🔥 ALTA", "MEDIUM": "✅ MEDIA", "LOW": "👀 BAJA"}.get(confidence.upper(), "")
    trigger_line = f"\n📊 *Señal:* {trigger}" if trigger else ""
    conf_line = f"\n🎯 *Confianza IA:* {conf_label}" if conf_label else ""
    _send(
        f"🟢 *SEÑAL DE ENTRADA* — {symbol}"
        f"{trigger_line}"
        f"{conf_line}"
        f"\n\n💬 _\"{reasoning}\"_"
        f"\n\n💰 Precio: `{entry:,.4f}` USDT"
        f"\n🎯 TP ref: `{tp:,.4f}` *(+{tp_pct:.2f}%)*"
        f"\n🛡️ SL ref: `{sl:,.4f}` *(-{sl_pct:.2f}%)*"
        f"\n\n⚡ _El bot entró. Decide si operas manualmente._"
    )


def notify_close(symbol: str, entry: float, exit_price: float,
                 pnl: float, reason: str, total_pnl: float) -> None:
    emoji = "✅" if pnl >= 0 else "❌"
    pnl_sign = "+" if pnl >= 0 else ""
    total_sign = "+" if total_pnl >= 0 else ""
    pct = (exit_price / entry - 1) * 100
    pct_sign = "+" if pct >= 0 else ""
    reason_labels = {
        "TAKE_PROFIT": "🎯 Take Profit alcanzado",
        "STOP_LOSS":   "🛡️ Stop Loss activado",
    }
    reason_str = reason_labels.get(reason, f"🤖 IA cerró ({reason})")
    tip = "💡 _Si estabas en posición, considera salir._" if pnl < 0 else "💡 _Buen momento para asegurar ganancias._"
    _send(
        f"{emoji} *SEÑAL DE SALIDA* — {symbol}\n"
        f"Motivo: {reason_str}\n"
        f"\nEntrada: `{entry:,.4f}` → Salida: `{exit_price:,.4f}` *({pct_sign}{pct:.2f}%)*\n"
        f"PnL bot: `{pnl_sign}{pnl:.4f}` USDT\n"
        f"PnL total: `{total_sign}{total_pnl:.4f}` USDT\n"
        f"\n{tip}"
    )


def notify_lesson(symbol: str, lesson: str) -> None:
    _send(f"💡 *Lesson* — {symbol}\n_{lesson}_")


def notify_error(symbol: str, error: str) -> None:
    _send(f"⚠️ *Error* — {symbol}\n`{error}`")


def notify_report(state: dict) -> None:
    from datetime import datetime, timezone
    from bot import state as state_mod

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    total = state_mod.total_pnl(state)
    total_sign = "+" if total >= 0 else ""
    total_emoji = "📈" if total > 0 else ("📉" if total < 0 else "➡️")
    balance = state.get("balance_usdt", 0.0)

    lines = [
        f"📊 *JD Bot — Reporte* | {now}",
        f"💰 Balance: `{balance:,.2f}` USDT",
        f"{total_emoji} PnL total: `{total_sign}{total:.4f}` USDT",
        "",
    ]

    for symbol, p in state.get("pairs", {}).items():
        stats  = p.get("stats", {})
        wins   = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        pnl    = stats.get("total_pnl", 0.0)
        signal = p.get("last_ai_signal") or {}

        # Last known price from price_history
        ph = p.get("price_history", [])
        price_str = f"`{ph[-1]['p']:,.4f}`" if ph else "—"

        open_trade = p.get("open_trade")
        if open_trade:
            entry  = open_trade["entry_price"]
            tp     = open_trade["take_profit"]
            sl     = open_trade["stop_loss"]
            last_p = ph[-1]["p"] if ph else entry
            unrealised = (last_p - entry) * open_trade["quantity"]
            u_sign = "+" if unrealised >= 0 else ""
            lines.append(
                f"🟡 *{symbol}* — EN POSICIÓN\n"
                f"   Entrada: `{entry:,.4f}` | Precio: {price_str}\n"
                f"   TP: `{tp:,.4f}` | SL: `{sl:,.4f}`\n"
                f"   PnL latente: `{u_sign}{unrealised:.4f}` USDT"
            )
        else:
            sig_txt = signal.get("decision", "—")
            conf    = signal.get("confidence", "")
            sig_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(sig_txt, "⚪")
            lines.append(
                f"{sig_emoji} *{symbol}* | {sig_txt} ({conf}) | {price_str}\n"
                f"   {wins}W/{losses}L | PnL: `{'+' if pnl>=0 else ''}{pnl:.4f}` USDT"
            )

    _send("\n".join(lines))
