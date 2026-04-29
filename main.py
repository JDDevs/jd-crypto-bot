"""
Entry point for the JD Crypto Bot.

Usage:
    python main.py            # live / testnet trading
    python backtest.py        # historical backtest
"""
import logging
import colorlog
from bot.exchange import build_exchange
from bot.trader import Trader


def setup_logging() -> None:
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    ))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main() -> None:
    setup_logging()
    exchange = build_exchange()
    trader = Trader(exchange)
    trader.run()


if __name__ == "__main__":
    main()
