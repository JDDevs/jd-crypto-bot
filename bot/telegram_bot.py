"""
Telegram bidirectional bot listener.

Polls Telegram's getUpdates API in a background daemon thread.
All commands and free-form messages are restricted to the configured
TELEGRAM_CHAT_ID — any other sender is silently ignored.

Supported commands
------------------
/ayuda      — list available commands
/estado     — current bot status (balance, open positions)
/config     — show all configurable parameters and their current values
/set P V    — change parameter P to value V at runtime (no restart needed)
/porque     — AI-powered analysis: why hasn't the bot invested?
/mercado    — AI overview of current market conditions
/reporte    — send the periodic report right now
<free text> — ask anything; the bot answers via AI with full context
"""
import logging
import threading
import time
import httpx

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED

log = logging.getLogger(__name__)
_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramListener:
    def __init__(self, trader=None) -> None:
        self._trader = trader
        self._offset: int = 0
        self._client = httpx.Client(timeout=45)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not TELEGRAM_ENABLED or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            log.info(
                "Telegram listener disabled "
                "(set TELEGRAM_ENABLED=true, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID in .env)"
            )
            return
        t = threading.Thread(target=self._poll_loop, daemon=True, name="tg-listener")
        t.start()
        log.info("Telegram listener started — waiting for commands in chat %s", TELEGRAM_CHAT_ID)

    # ------------------------------------------------------------------
    # Long-polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while True:
            try:
                updates = self._get_updates()
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id != str(TELEGRAM_CHAT_ID):
                        continue
                    text = msg.get("text", "").strip()
                    if text:
                        self._handle_message(text)
            except Exception as e:
                log.warning("Telegram poll error: %s — retrying in 5s", e)
                time.sleep(5)

    def _get_updates(self) -> list[dict]:
        url = _API.format(token=TELEGRAM_TOKEN, method="getUpdates")
        resp = self._client.get(url, params={
            "offset": self._offset,
            "timeout": 30,
            "allowed_updates": ["message"],
        })
        data = resp.json()
        return data.get("result", []) if data.get("ok") else []

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def _handle_message(self, text: str) -> None:
        low = text.lower().lstrip()
        if low.startswith("/ayuda") or low.startswith("/help"):
            self._cmd_help()
        elif low.startswith("/estado") or low.startswith("/status"):
            self._cmd_status()
        elif low.startswith("/config"):
            self._cmd_config()
        elif low.startswith("/set"):
            parts = text.split(None, 2)
            if len(parts) < 3:
                self._send(
                    "Uso: `/set PARAMETRO VALOR`\n"
                    "Ejemplo: `/set AI_CONFIDENCE_THRESHOLD MEDIUM`\n"
                    "Usa /config para ver todos los parámetros disponibles."
                )
            else:
                self._cmd_set(parts[1], parts[2])
        elif low.startswith("/porque") or low.startswith("/porqué") or low.startswith("/why"):
            self._cmd_why()
        elif low.startswith("/mercado") or low.startswith("/market"):
            self._cmd_market()
        elif low.startswith("/reporte") or low.startswith("/report"):
            self._cmd_report()
        elif low.startswith("/"):
            self._send("Comando desconocido. Escribe /ayuda para ver los disponibles.")
        else:
            self._cmd_chat(text)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_help(self) -> None:
        self._send(
            "🤖 *JD Crypto Bot — Comandos*\n\n"
            "*/estado* — Balance, posiciones abiertas y señales recientes\n"
            "*/config* — Ver todos los parámetros configurables\n"
            "*/set PARAM VALOR* — Cambiar un parámetro sin reiniciar\n"
            "*/porque* — ¿Por qué no ha invertido? (análisis con IA)\n"
            "*/mercado* — Resumen del mercado actual\n"
            "*/reporte* — Generar reporte ahora\n"
            "*/ayuda* — Esta ayuda\n\n"
            "_También puedes escribirme en lenguaje natural y te respondo con IA._\n\n"
            "*Ejemplos de /set:*\n"
            "`/set AI_CONFIDENCE_THRESHOLD MEDIUM`\n"
            "`/set FEAR_GREED_MIN 15`\n"
            "`/set VOLUME_FILTER_ENABLED false`"
        )

    def _cmd_status(self) -> None:
        from bot import notifier, state as state_mod
        notifier.notify_report(state_mod.load())

    def _cmd_config(self) -> None:
        import bot.runtime_config as rc
        cfg = rc.all_values()
        overrides = rc.active_overrides()

        lines = ["⚙️ *Configuración activa*\n"]
        for k, v in cfg.items():
            marker = " ✏️" if k in overrides else ""
            lines.append(f"`{k}` = `{v}`{marker}")

        if overrides:
            lines.append(
                "\n_✏️ = valor modificado en tiempo real_\n"
                "_Los cambios se pierden al reiniciar. Edita .env para hacerlos permanentes._"
            )
        lines.append("\nUsa `/set PARAM VALOR` para cambiar cualquier parámetro.")
        self._send("\n".join(lines))

    def _cmd_set(self, param: str, value: str) -> None:
        import bot.runtime_config as rc
        ok, msg = rc.set_override(param, value)
        self._send(msg)

    def _cmd_why(self) -> None:
        from bot.ai_analyst import chat
        self._send("🔍 _Analizando por qué el bot no ha invertido..._")
        question = (
            "¿Por qué el bot no ha realizado ninguna inversión recientemente? "
            "Analiza cada filtro activo (Fear&Greed, VWAP, volumen, blackout horario, "
            "cooldown, umbral de confianza IA) y las condiciones del mercado para cada par. "
            "Sé específico e indica qué tendría que cambiar para que el bot invierta."
        )
        try:
            response = chat(question, self._build_snapshot())
            self._send(response)
        except Exception as e:
            log.warning("_cmd_why error: %s", e)
            self._send("Error al consultar la IA. Intenta de nuevo.")

    def _cmd_market(self) -> None:
        from bot.ai_analyst import chat
        self._send("📊 _Analizando el mercado..._")
        question = (
            "¿Cómo está el mercado actualmente? Resume el outlook macro, "
            "el índice Fear & Greed, las últimas señales de la IA por par "
            "y qué condiciones están afectando las decisiones del bot."
        )
        try:
            response = chat(question, self._build_snapshot())
            self._send(response)
        except Exception as e:
            log.warning("_cmd_market error: %s", e)
            self._send("Error al consultar la IA. Intenta de nuevo.")

    def _cmd_report(self) -> None:
        from bot import notifier, state as state_mod
        notifier.notify_report(state_mod.load())

    def _cmd_chat(self, text: str) -> None:
        from bot.ai_analyst import chat
        try:
            response = chat(text, self._build_snapshot())
            self._send(response)
        except Exception as e:
            log.warning("_cmd_chat error: %s", e)
            self._send("Error al consultar la IA. Intenta de nuevo.")

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> dict:
        from bot import state as state_mod
        from datetime import datetime, timezone

        state = state_mod.load()
        snapshot: dict = {
            "balance":      state.get("balance_usdt", 0.0),
            "utc_hour":     datetime.now(timezone.utc).hour,
            "macro_outlook": getattr(self._trader, "_macro_outlook", "NEUTRAL"),
            "fear_greed":   getattr(self._trader, "_fear_greed_value", 50),
            "pairs":        {},
        }

        for symbol, pair in state.get("pairs", {}).items():
            ph = pair.get("price_history", [])
            snapshot["pairs"][symbol] = {
                "open_trade":     pair.get("open_trade"),
                "current_price":  ph[-1]["p"] if ph else None,
                "last_ai_signal": pair.get("last_ai_signal"),
                "last_skip":      pair.get("last_skip"),
                "stats":          pair.get("stats", {}),
                "lessons_learned": pair.get("lessons_learned", []),
            }
        return snapshot

    # ------------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------------

    def _send(self, text: str) -> None:
        try:
            url = _API.format(token=TELEGRAM_TOKEN, method="sendMessage")
            self._client.post(url, json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       text,
                "parse_mode": "Markdown",
            })
        except Exception as e:
            log.warning("Telegram send error: %s", e)
