from dataclasses import dataclass
import bot.runtime_config as rc


@dataclass
class TradeSetup:
    entry_price: float
    take_profit: float
    stop_loss: float
    quantity: float
    risk_amount: float

    def __str__(self) -> str:
        tp_pct = float(rc.get("TAKE_PROFIT_PCT")) * 100
        sl_pct = float(rc.get("STOP_LOSS_PCT")) * 100
        return (
            f"Entry={self.entry_price:.4f} | "
            f"TP={self.take_profit:.4f} (+{tp_pct:.2f}%) | "
            f"SL={self.stop_loss:.4f} (-{sl_pct:.2f}%) | "
            f"Qty={self.quantity:.6f} | Risk={self.risk_amount:.2f} USDT"
        )


def build_trade_setup(balance_usdt: float, entry_price: float) -> TradeSetup:
    risk_per_trade = float(rc.get("RISK_PER_TRADE"))
    take_profit_pct = float(rc.get("TAKE_PROFIT_PCT"))
    stop_loss_pct = float(rc.get("STOP_LOSS_PCT"))
    risk_amount = balance_usdt * risk_per_trade
    quantity = risk_amount / (entry_price * stop_loss_pct)
    take_profit = entry_price * (1 + take_profit_pct)
    stop_loss = entry_price * (1 - stop_loss_pct)
    return TradeSetup(entry_price, take_profit, stop_loss, quantity, risk_amount)


def trailing_stop_price(setup: TradeSetup, highest_price: float) -> float | None:
    """Returns the trailing stop level once armed, else None."""
    if not rc.get("TRAILING_STOP_ENABLED"):
        return None
    activation_price = setup.entry_price * (1 + float(rc.get("TRAILING_ACTIVATE_PCT")))
    if highest_price < activation_price:
        return None
    return highest_price * (1 - float(rc.get("TRAILING_DISTANCE_PCT")))


def should_exit(current_price: float, setup: TradeSetup,
                highest_price: float = 0.0) -> tuple[bool, str]:
    """Returns (should_exit, reason)."""
    if current_price <= setup.stop_loss:
        return True, "STOP_LOSS"
    if current_price >= setup.take_profit:
        return True, "TAKE_PROFIT"
    trail = trailing_stop_price(setup, highest_price)
    if trail is not None and current_price <= trail:
        return True, "TRAILING_STOP"
    return False, ""
