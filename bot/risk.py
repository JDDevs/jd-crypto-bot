from dataclasses import dataclass
from config import RISK_PER_TRADE, TAKE_PROFIT_PCT, STOP_LOSS_PCT


@dataclass
class TradeSetup:
    entry_price: float
    take_profit: float
    stop_loss: float
    quantity: float
    risk_amount: float

    def __str__(self) -> str:
        return (
            f"Entry={self.entry_price:.4f} | "
            f"TP={self.take_profit:.4f} (+{TAKE_PROFIT_PCT*100:.2f}%) | "
            f"SL={self.stop_loss:.4f} (-{STOP_LOSS_PCT*100:.2f}%) | "
            f"Qty={self.quantity:.6f} | Risk={self.risk_amount:.2f} USDT"
        )


def build_trade_setup(balance_usdt: float, entry_price: float) -> TradeSetup:
    risk_amount = balance_usdt * RISK_PER_TRADE
    quantity = risk_amount / (entry_price * STOP_LOSS_PCT)
    take_profit = entry_price * (1 + TAKE_PROFIT_PCT)
    stop_loss = entry_price * (1 - STOP_LOSS_PCT)
    return TradeSetup(entry_price, take_profit, stop_loss, quantity, risk_amount)


def should_exit(current_price: float, setup: TradeSetup) -> tuple[bool, str]:
    """Returns (should_exit, reason)."""
    if current_price >= setup.take_profit:
        return True, "TAKE_PROFIT"
    if current_price <= setup.stop_loss:
        return True, "STOP_LOSS"
    return False, ""
