import time
import logging
import ccxt
from dataclasses import asdict
from config import SYMBOLS, TIMEFRAME, LOOP_SLEEP
from bot.exchange import (
    fetch_candles, fetch_balance, fetch_ticker,
    place_market_order,
)
from bot.strategy import Signal
from bot.ai_analyst import analyse, reflect, is_actionable
from bot.risk import build_trade_setup, should_exit, TradeSetup
from bot import state as state_mod

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
        log.info("Bot started — pairs=%s timeframe=%s model=groq", SYMBOLS, TIMEFRAME)
        while True:
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
    # Per-symbol iteration
    # ------------------------------------------------------------------

    def _tick(self, symbol: str) -> None:
        df = fetch_candles(self.exchange, symbol)
        pair_state = self.state["pairs"][symbol]

        # Record latest close for price-history chart
        state_mod.record_price(self.state, symbol, df.iloc[-1]["close"])

        if pair_state["open_trade"]:
            self._manage_open_trade(symbol, df)
            return

        ai = analyse(df, symbol, pair_state)
        state_mod.record_ai_signal(self.state, symbol, ai.signal.value, ai.confidence, ai.reasoning)
        state_mod.save(self.state)

        if ai.signal == Signal.BUY and is_actionable(ai):
            self._open_trade(symbol, df.iloc[-1]["close"], ai.reasoning)
        elif ai.signal == Signal.SELL and is_actionable(ai):
            log.info("[%s SKIP SELL] No open position to close.", symbol)
        else:
            log.info("[%s HOLD] %s", symbol, ai)

    def _open_trade(self, symbol: str, price: float, reasoning: str) -> None:
        balance = fetch_balance(self.exchange, "USDT")
        if balance < 10:
            log.warning("[%s] Insufficient balance: %.2f USDT", symbol, balance)
            return

        # Split balance equally across configured pairs to bound exposure
        allocated = balance / max(len(SYMBOLS), 1)
        setup = build_trade_setup(allocated, price)
        log.info("[%s BUY] %s | Reason: %s", symbol, setup, reasoning)
        place_market_order(self.exchange, symbol, "buy", setup.quantity)

        state_mod.record_open(self.state, symbol, setup, reasoning)
        state_mod.save(self.state)

    def _manage_open_trade(self, symbol: str, df) -> None:
        setup = _setup_from_dict(self.state["pairs"][symbol]["open_trade"])
        ticker = fetch_ticker(self.exchange, symbol)
        current_price = float(ticker["last"])

        exit_flag, reason = should_exit(current_price, setup)
        if exit_flag:
            self._close_trade(symbol, setup, current_price, reason)
            return

        # AI early-exit check
        ai = analyse(df, symbol, self.state["pairs"][symbol])
        state_mod.record_ai_signal(self.state, symbol, ai.signal.value, ai.confidence, ai.reasoning)
        state_mod.save(self.state)

        if ai.signal == Signal.SELL and is_actionable(ai):
            self._close_trade(symbol, setup, current_price, f"AI_SELL ({ai.confidence})")
        else:
            log.info(
                "[%s HOLD TRADE] price=%.4f TP=%.4f SL=%.4f | %s",
                symbol, current_price, setup.take_profit, setup.stop_loss, ai,
            )

    def _close_trade(self, symbol: str, setup: TradeSetup, price: float, reason: str) -> None:
        log.info("[%s SELL] reason=%s price=%.4f", symbol, reason, price)
        place_market_order(self.exchange, symbol, "sell", setup.quantity)

        pnl = (price - setup.entry_price) * setup.quantity
        closed = state_mod.record_close(self.state, symbol, price, setup.quantity, pnl, reason)
        state_mod.save(self.state)

        stats = self.state["pairs"][symbol]["stats"]
        log.info(
            "[%s CLOSED] PnL=%.4f USDT | Wins=%d Losses=%d Pair PnL=%.4f | Total=%.4f",
            symbol, pnl, stats["wins"], stats["losses"], stats["total_pnl"],
            state_mod.total_pnl(self.state),
        )

        # Self-reflection: ask Groq for a lesson learned
        lesson = reflect(symbol, closed)
        if lesson:
            state_mod.record_lesson(self.state, symbol, lesson)
            state_mod.save(self.state)
