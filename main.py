"""
Entry point for the JD Crypto Bot.

Usage:
    python main.py            # live / testnet trading + dashboard
    python backtest.py        # historical backtest
"""
import logging
import threading
import time
import colorlog
from config import DASHBOARD_ENABLED, DASHBOARD_HOST, DASHBOARD_PORT
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


def start_dashboard() -> None:
    from bot.dashboard import run as run_dashboard
    t = threading.Thread(
        target=run_dashboard, args=(DASHBOARD_HOST, DASHBOARD_PORT),
        daemon=True, name="dashboard",
    )
    t.start()


def start_report_thread(interval_seconds: int = 300) -> None:
    def _loop() -> None:
        from bot import state as state_mod
        from bot.notifier import notify_report
        while True:
            time.sleep(interval_seconds)
            try:
                notify_report(state_mod.load())
            except Exception as e:
                logging.getLogger(__name__).warning("Report failed: %s", e)

    t = threading.Thread(target=_loop, daemon=True, name="report")
    t.start()


def main() -> None:
    setup_logging()
    if DASHBOARD_ENABLED:
        start_dashboard()
    start_report_thread(interval_seconds=300)  # every 5 minutes
    exchange = build_exchange()
    Trader(exchange).run()


if __name__ == "__main__":
    main()
