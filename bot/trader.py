import time
import logging
import httpx
import ccxt
from datetime import datetime, timezone
from config import (
    SYMBOLS, TIMEFRAME, LOOP_SLEEP,
    AI_HOLD_PRICE_MOVE,
    VOLUME_FILTER_PERIODS,
    FEAR_GREED_TTL,
    SLIPPAGE_WARN_PCT,
    MACRO_CHECK_INTERVAL,
)
import bot.runtime_config as rc
from bot.exchange import (
    fetch_candles, fetch_balance, fetch_ticker,
    place_market_order,
)
from bot.strategy import Signal, evaluate
from bot.ai_analyst import analyse, reflect, is_actionable, macro_analysis
from bot.risk import build_trade_setup, should_exit, TradeSetup
from bot import state as state_mod
from bot import notifier

log = logging.getLogger(__name__)


def _setup_from_dict(d: dict) -> TradeSetup:
    return TradeSetup(
        entry_price=d["entry_price"],
        take_profit=d["take_profit"],
        stop_loss=d["stop_loss"],
        quantity=d["quantity"],
        risk_amount=d["risk_amount"],
    )


class Trader:
    def __init__(self, exchange: ccxt.Exchange):
        self.exchange = exchange
        self.state = state_mod.load()
        self._last_ai_check: dict[str, float] = {}   # symbol → timestamp of last in-position AI call
        self._last_ai_price: dict[str, float] = {}   # symbol → price at last in-position AI call
        self._last_close: dict[str, dict] = {}        # symbol → {"time": float, "price": float}
        self._fear_greed_value: int = 50              # cached Fear & Greed index (50 = neutral)
        self._fear_greed_last: float = 0
        self._macro_outlook: str = "NEUTRAL"
        self._macro_last_check: float = 0
        removed = state_mod.cleanup_orphans(self.state, SYMBOLS)
        if removed:
            log.info("Cleaned up %d orphan pair(s) no longer in SYMBOLS", removed)
        for sym in SYMBOLS:
            state_mod.ensure_pair(self.state, sym)
        state_mod.save(self.state)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        log.info("Bot started — pairs=%s timeframe=%s", SYMBOLS, TIMEFRAME)
        while True:
            try:
                balance = fetch_balance(self.exchange, "USDT")
                state_mod.record_balance(self.state, balance)
            except Exception:
                pass
            self._update_macro()
            for symbol in SYMBOLS:
                try:
                    self._tick(symbol)
                except ccxt.NetworkError as e:
                    log.warning("[%s] Network error: %s", symbol, e)
                except ccxt.ExchangeError as e:
                    log.error("[%s] Exchange error: %s", symbol, e)
                except KeyboardInterrupt:
                    log.info("Bot stopped by user.")
                    return
                except Exception as e:
                    log.exception("[%s] Unexpected error: %s", symbol, e)
            time.sleep(LOOP_SLEEP)

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _count_open_trades(self) -> int:
        return sum(1 for p in self.state["pairs"].values() if p.get("open_trade"))

    def _get_fear_greed(self) -> int:
        now = time.time()
        if now - self._fear_greed_last > FEAR_GREED_TTL:
            try:
                resp = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=5)
                self._fear_greed_value = int(resp.json()["data"][0]["value"])
                self._fear_greed_last = now
                log.info("Fear & Greed index: %d", self._fear_greed_value)
            except Exception as e:
                log.warning("Fear & Greed fetch failed: %s", e)
        return self._fear_greed_value

    def _update_macro(self) -> None:
        now = time.time()
        if now - self._macro_last_check < MACRO_CHECK_INTERVAL:
            return
        try:
            symbol_data = {}
            for sym in SYMBOLS:
                pair = self.state["pairs"].get(sym, {})
                ph = pair.get("price_history", [])
                sig = pair.get("last_ai_signal") or {}
                symbol_data[sym] = {
                    "last_price":      ph[-1]["p"] if ph else 0,
                    "last_signal":     sig.get("decision", "HOLD"),
                    "last_confidence": sig.get("confidence", "LOW"),
                }
            outlook, reasoning = macro_analysis(symbol_data, self._fear_greed_value)
            self._macro_outlook = outlook
            self._macro_last_check = now
        except Exception as e:
            log.warning("Macro update failed: %s", e)

    # ------------------------------------------------------------------
    # Per-symbol iteration
    # ------------------------------------------------------------------

    def _tick(self, symbol: str) -> None:
        df = fetch_candles(self.exchange, symbol)
        pair_state = self.state["pairs"][symbol]

        # Record latest close for price-history chart
        state_mod.record_price(self.state, symbol, df.iloc[-1]["close"])
        state_mod.save(self.state)

        if pair_state["open_trade"]:
            self._manage_open_trade(symbol, df)
            return

        # Pre-filter: run cheap rule-based check before calling the AI.
        # If indicators show no signal at all, skip the API call entirely.
        rule = evaluate(df)
        if rule.signal == Signal.HOLD:
            log.debug("[%s] Rule-based HOLD — no AI call needed", symbol)
            return

        current_price = df.iloc[-1]["close"]

        # --- Gate 1: max concurrent positions ---
        max_trades = int(rc.get("MAX_OPEN_TRADES"))
        open_count = self._count_open_trades()
        if open_count >= max_trades:
            log.debug("[%s] Max open trades (%d) reached", symbol, max_trades)
            state_mod.record_skip_reason(
                self.state, symbol, "MAX_OPEN_TRADES",
                f"{open_count}/{max_trades} posiciones abiertas",
            )
            state_mod.save(self.state)
            return

        # --- Gate 2: trading hours blackout ---
        if rc.get("TRADING_BLACKOUT_ENABLED"):
            hour = datetime.now(timezone.utc).hour
            bs = int(rc.get("BLACKOUT_START"))
            be = int(rc.get("BLACKOUT_END"))
            in_blackout = (hour >= bs or hour < be)
            if in_blackout:
                log.debug("[%s BLACKOUT] UTC %02d:xx — no new entries", symbol, hour)
                state_mod.record_skip_reason(
                    self.state, symbol, "BLACKOUT",
                    f"UTC {hour:02d}:xx (bloqueo {bs:02d}:00–{be:02d}:00)",
                )
                state_mod.save(self.state)
                return

        # --- Gate 3: re-entry protection ---
        last_close = self._last_close.get(symbol)
        if last_close:
            elapsed = time.time() - last_close["time"]
            cooldown = int(rc.get("RE_ENTRY_COOLDOWN"))
            if elapsed < cooldown:
                log.info("[%s COOLDOWN] %.0fs since last close (need %ds) — skipping",
                         symbol, elapsed, cooldown)
                state_mod.record_skip_reason(
                    self.state, symbol, "COOLDOWN",
                    f"{elapsed:.0f}s desde último cierre (necesita {cooldown}s)",
                )
                state_mod.save(self.state)
                return
            buf = float(rc.get("RE_ENTRY_PRICE_BUFFER"))
            if current_price > last_close["price"] * (1 + buf):
                log.info("[%s PRICE-BLOCK] price=%.4f > exit=%.4f+%.1f%% — won't chase",
                         symbol, current_price, last_close["price"], buf * 100)
                state_mod.record_skip_reason(
                    self.state, symbol, "PRECIO_BLOQUEO",
                    f"precio {current_price:.4f} > salida {last_close['price']:.4f}+{buf*100:.1f}%",
                )
                state_mod.save(self.state)
                return

        # --- Gate 4: volume filter ---
        if rc.get("VOLUME_FILTER_ENABLED") and len(df) > VOLUME_FILTER_PERIODS + 1:
            vol_avg = df["volume"].iloc[-(VOLUME_FILTER_PERIODS + 1):-1].mean()
            mult = float(rc.get("VOLUME_FILTER_MULT"))
            if df.iloc[-1]["volume"] < vol_avg * mult:
                log.debug("[%s VOL-FILTER] vol=%.2f < avg=%.2f×%.1f — skipping",
                          symbol, df.iloc[-1]["volume"], vol_avg, mult)
                state_mod.record_skip_reason(
                    self.state, symbol, "VOLUMEN",
                    f"vol={df.iloc[-1]['volume']:.2f} < avg={vol_avg:.2f}×{mult}",
                )
                state_mod.save(self.state)
                return

        # --- Gate 5: VWAP filter (only BUY above session VWAP) ---
        if rc.get("VWAP_FILTER_ENABLED") and rule.signal == Signal.BUY:
            typical = (df["high"] + df["low"] + df["close"]) / 3
            vwap = (typical * df["volume"]).sum() / df["volume"].sum()
            if current_price < vwap:
                log.debug("[%s VWAP-FILTER] price=%.4f < VWAP=%.4f — skipping",
                          symbol, current_price, vwap)
                state_mod.record_skip_reason(
                    self.state, symbol, "VWAP",
                    f"precio {current_price:.4f} < VWAP {vwap:.4f}",
                )
                state_mod.save(self.state)
                return

        # --- Gate 6: Fear & Greed index ---
        if rc.get("FEAR_GREED_ENABLED") and rule.signal == Signal.BUY:
            fg = self._get_fear_greed()
            fg_min = int(rc.get("FEAR_GREED_MIN"))
            fg_max = int(rc.get("FEAR_GREED_MAX"))
            if fg < fg_min:
                log.info("[%s FG-FILTER] Fear&Greed=%d (Extreme Fear) — no BUY", symbol, fg)
                state_mod.record_skip_reason(
                    self.state, symbol, "FEAR_GREED",
                    f"Fear&Greed={fg} < mínimo {fg_min} (Miedo Extremo)",
                )
                state_mod.save(self.state)
                return
            if fg > fg_max:
                log.info("[%s FG-FILTER] Fear&Greed=%d (Extreme Greed) — no BUY", symbol, fg)
                state_mod.record_skip_reason(
                    self.state, symbol, "FEAR_GREED",
                    f"Fear&Greed={fg} > máximo {fg_max} (Codicia Extrema)",
                )
                state_mod.save(self.state)
                return

        # Macro outlook → tighten confidence threshold when market looks bad
        effective_threshold = "HIGH" if self._macro_outlook == "UNFAVORABLE" else None

        # All gates passed → ask the AI for confirmation
        log.info("[%s] Rule signal=%s RSI=%.1f — consulting AI...", symbol, rule.signal.value, rule.rsi)
        ai = analyse(df, symbol, pair_state)
        state_mod.record_ai_signal(self.state, symbol, ai.signal.value, ai.confidence, ai.reasoning)
        state_mod.save(self.state)

        if ai.signal == Signal.BUY and is_actionable(ai, effective_threshold):
            self._open_trade(symbol, current_price, ai.reasoning, ai.confidence, rule.trigger)
        elif ai.signal == Signal.SELL and is_actionable(ai):
            log.info("[%s SKIP SELL] No open position to close.", symbol)
        else:
            log.info("[%s HOLD] %s", symbol, ai)

    def _open_trade(self, symbol: str, price: float, reasoning: str,
                    confidence: str = "", trigger: str = "") -> None:
        balance = fetch_balance(self.exchange, "USDT")
        if balance < 10:
            log.warning("[%s] Insufficient balance: %.2f USDT", symbol, balance)
            return

        allocated = balance / max(len(SYMBOLS), 1)
        setup = build_trade_setup(allocated, price)
        log.info("[%s BUY] %s | Reason: %s", symbol, setup, reasoning)
        order = place_market_order(self.exchange, symbol, "buy", setup.quantity)

        # Slippage detection
        fill_price = float(order.get("average") or order.get("price") or price)
        slippage = abs(fill_price - price) / price
        if slippage > SLIPPAGE_WARN_PCT:
            log.warning("[%s] High slippage: signal=%.4f fill=%.4f (%.3f%%)",
                        symbol, price, fill_price, slippage * 100)

        state_mod.record_open(self.state, symbol, setup, reasoning)
        state_mod.save(self.state)
        notifier.notify_buy(symbol, setup.entry_price, setup.take_profit,
                            setup.stop_loss, setup.quantity, reasoning, confidence, trigger)

    def _manage_open_trade(self, symbol: str, df) -> None:
        open_trade = self.state["pairs"][symbol]["open_trade"]
        setup = _setup_from_dict(open_trade)
        ticker = fetch_ticker(self.exchange, symbol)
        current_price = float(ticker["last"])

        # Update peak price for trailing stop (backfills field if missing)
        highest = open_trade.get("highest_price", setup.entry_price)
        if current_price > highest:
            highest = current_price
            open_trade["highest_price"] = highest
            state_mod.save(self.state)

        # SL / TP / Trailing exit — no AI call needed
        exit_flag, reason = should_exit(current_price, setup, highest)
        if exit_flag:
            self._close_trade(symbol, setup, current_price, reason)
            return

        # Active AI monitoring — check every AI_HOLD_CHECK_INTERVAL seconds
        # or whenever price moves AI_HOLD_PRICE_MOVE from the last consulted price
        now = time.time()
        last_check = self._last_ai_check.get(symbol, 0)
        last_price = self._last_ai_price.get(symbol, current_price)
        time_elapsed = (now - last_check) >= int(rc.get("AI_HOLD_CHECK_INTERVAL"))
        price_moved = abs(current_price - last_price) / last_price >= AI_HOLD_PRICE_MOVE

        if time_elapsed or price_moved:
            log.info("[%s IN-POSITION] Consulting AI (elapsed=%ds, Δprice=%.3f%%)",
                     symbol, int(now - last_check),
                     abs(current_price - last_price) / last_price * 100)
            ai = analyse(df, symbol, self.state["pairs"][symbol])
            state_mod.record_ai_signal(self.state, symbol, ai.signal.value, ai.confidence, ai.reasoning)
            state_mod.save(self.state)
            self._last_ai_check[symbol] = now
            self._last_ai_price[symbol] = current_price
            if ai.signal == Signal.SELL and is_actionable(ai):
                self._close_trade(symbol, setup, current_price, f"AI_SELL ({ai.confidence})")
                return

        log.info(
            "[%s HOLD TRADE] price=%.4f TP=%.4f SL=%.4f trailing_peak=%.4f",
            symbol, current_price, setup.take_profit, setup.stop_loss, highest,
        )

    def _close_trade(self, symbol: str, setup: TradeSetup, price: float, reason: str) -> None:
        log.info("[%s SELL] reason=%s price=%.4f", symbol, reason, price)
        place_market_order(self.exchange, symbol, "sell", setup.quantity)

        pnl = (price - setup.entry_price) * setup.quantity
        closed = state_mod.record_close(self.state, symbol, price, setup.quantity, pnl, reason)
        state_mod.save(self.state)
        self._last_close[symbol] = {"time": time.time(), "price": price}

        stats = self.state["pairs"][symbol]["stats"]
        total = state_mod.total_pnl(self.state)
        log.info(
            "[%s CLOSED] PnL=%.4f USDT | Wins=%d Losses=%d Pair PnL=%.4f | Total=%.4f",
            symbol, pnl, stats["wins"], stats["losses"], stats["total_pnl"], total,
        )
        notifier.notify_close(symbol, setup.entry_price, price, pnl, reason, total)

        # Self-reflection — only 1 extra call per closed trade
        lesson = reflect(symbol, closed)
        if lesson:
            state_mod.record_lesson(self.state, symbol, lesson)
            state_mod.save(self.state)
            notifier.notify_lesson(symbol, lesson)
