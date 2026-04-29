import time
import logging
import ccxt
from config import SYMBOL, TIMEFRAME, LOOP_SLEEP
from bot.exchange import (
    fetch_candles, fetch_balance, fetch_ticker,
    place_market_order,
)
from bot.strategy import Signal
from bot.ai_analyst import analyse, is_actionable
from bot.risk import build_trade_setup, should_exit, TradeSetup

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, exchange: ccxt.Exchange):
        self.exchange = exchange
        self.open_trade: TradeSetup | None = None
        self.stats = {"wins": 0, "losses": 0, "total_pnl": 0.0}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        log.info("Bot started — symbol=%s timeframe=%s model=groq", SYMBOL, TIMEFRAME)
        while True:
            try:
                self._tick()
            except ccxt.NetworkError as e:
                log.warning("Network error: %s — retrying in %ds", e, LOOP_SLEEP)
            except ccxt.ExchangeError as e:
                log.error("Exchange error: %s", e)
            except KeyboardInterrupt:
                log.info("Bot stopped by user. Stats: %s", self.stats)
                break
            except Exception as e:
                log.exception("Unexpected error: %s", e)
            time.sleep(LOOP_SLEEP)

    # ------------------------------------------------------------------
    # Single iteration
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        df = fetch_candles(self.exchange)

        if self.open_trade:
            self._manage_open_trade(df)
            return

        if not self._can_open():
            return

        ai = analyse(df)

        if ai.signal == Signal.BUY and is_actionable(ai):
            self._open_trade(df.iloc[-1]["close"], ai.reasoning)
        elif ai.signal == Signal.SELL and is_actionable(ai):
            log.info("[SKIP SELL] No open position to close.")
        else:
            log.info("[HOLD] %s", ai)

    def _can_open(self) -> bool:
        return self.open_trade is None

    def _open_trade(self, price: float, reasoning: str) -> None:
        balance = fetch_balance(self.exchange, "USDT")
        if balance < 10:
            log.warning("Insufficient balance: %.2f USDT", balance)
            return

        setup = build_trade_setup(balance, price)
        log.info("[BUY] %s | Reason: %s", setup, reasoning)
        place_market_order(self.exchange, SYMBOL, "buy", setup.quantity)
        self.open_trade = setup

    def _manage_open_trade(self, df) -> None:
        ticker = fetch_ticker(self.exchange)
        current_price = float(ticker["last"])
        exit_flag, reason = should_exit(current_price, self.open_trade)

        if exit_flag:
            self._close_trade(current_price, reason)
            return

        # Ask AI if we should exit early (bearish signal while in trade)
        ai = analyse(df)
        if ai.signal == Signal.SELL and is_actionable(ai):
            log.info("[AI EXIT] %s", ai)
            self._close_trade(current_price, f"AI_SELL ({ai.confidence}): {ai.reasoning}")
        else:
            log.info(
                "[HOLD TRADE] price=%.4f TP=%.4f SL=%.4f | AI: %s",
                current_price,
                self.open_trade.take_profit,
                self.open_trade.stop_loss,
                ai,
            )

    def _close_trade(self, price: float, reason: str) -> None:
        log.info("[SELL] reason=%s price=%.4f", reason, price)
        place_market_order(self.exchange, SYMBOL, "sell", self.open_trade.quantity)

        pnl = (price - self.open_trade.entry_price) * self.open_trade.quantity
        self.stats["total_pnl"] += pnl
        if pnl > 0:
            self.stats["wins"] += 1
        else:
            self.stats["losses"] += 1

        log.info(
            "[CLOSED] PnL=%.4f USDT | Wins=%d Losses=%d TotalPnL=%.4f",
            pnl,
            self.stats["wins"],
            self.stats["losses"],
            self.stats["total_pnl"],
        )
        self.open_trade = None
