"""
State persistence layer.

Stores per-pair state (open trade, stats, last AI signal) and a global
trade history in a single JSON file. The trader writes after every
event; the dashboard reads on every request.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILE = Path("state.json")
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict[str, Any]:
    return {"pairs": {}, "trade_history": []}


def load() -> dict[str, Any]:
    with _lock:
        if not STATE_FILE.exists():
            return _empty()
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return _empty()


def save(state: dict[str, Any]) -> None:
    with _lock:
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def ensure_pair(state: dict[str, Any], symbol: str) -> dict[str, Any]:
    if symbol not in state["pairs"]:
        state["pairs"][symbol] = {
            "open_trade": None,
            "stats": {"wins": 0, "losses": 0, "total_pnl": 0.0},
            "last_ai_signal": None,
            "price_history": [],
            "equity_history": [],
            "closed_trades": [],
            "lessons_learned": [],
        }
    else:
        # Backfill keys for older state files
        state["pairs"][symbol].setdefault("price_history", [])
        state["pairs"][symbol].setdefault("equity_history", [])
        state["pairs"][symbol].setdefault("closed_trades", [])
        state["pairs"][symbol].setdefault("lessons_learned", [])
    return state["pairs"][symbol]


def cleanup_orphans(state: dict[str, Any], valid_symbols: list[str]) -> int:
    """Remove pairs that are no longer in the configured SYMBOLS list."""
    valid = set(valid_symbols)
    orphans = [s for s in state["pairs"].keys() if s not in valid]
    for s in orphans:
        del state["pairs"][s]
    return len(orphans)


def record_price(state: dict[str, Any], symbol: str, price: float, max_points: int = 200) -> None:
    pair = ensure_pair(state, symbol)
    pair["price_history"].append({"t": _now(), "p": float(price)})
    pair["price_history"] = pair["price_history"][-max_points:]


def record_ai_signal(state: dict[str, Any], symbol: str,
                     decision: str, confidence: str, reasoning: str) -> None:
    pair = ensure_pair(state, symbol)
    pair["last_ai_signal"] = {
        "decision": decision,
        "confidence": confidence,
        "reasoning": reasoning,
        "timestamp": _now(),
    }


def record_open(state: dict[str, Any], symbol: str, setup: Any, reasoning: str) -> None:
    pair = ensure_pair(state, symbol)
    pair["open_trade"] = {
        "entry_price":     setup.entry_price,
        "take_profit":     setup.take_profit,
        "stop_loss":       setup.stop_loss,
        "quantity":        setup.quantity,
        "risk_amount":     setup.risk_amount,
        "opened_at":       _now(),
        "entry_reasoning": reasoning,
    }
    state["trade_history"].append({
        "timestamp": _now(),
        "symbol":    symbol,
        "side":      "BUY",
        "price":     setup.entry_price,
        "quantity":  setup.quantity,
        "reason":    reasoning,
        "pnl":       None,
    })


def record_close(state: dict[str, Any], symbol: str, price: float,
                 quantity: float, pnl: float, reason: str) -> dict[str, Any]:
    """Returns a dict describing the closed trade (used by reflect())."""
    pair = ensure_pair(state, symbol)
    open_trade = pair.get("open_trade") or {}
    closed = {
        "entry_price":     open_trade.get("entry_price"),
        "exit_price":      price,
        "quantity":        quantity,
        "pnl":             round(pnl, 6),
        "exit_reason":     reason,
        "entry_reasoning": open_trade.get("entry_reasoning", ""),
        "opened_at":       open_trade.get("opened_at"),
        "closed_at":       _now(),
    }

    pair["open_trade"] = None
    if pnl > 0:
        pair["stats"]["wins"] += 1
    else:
        pair["stats"]["losses"] += 1
    pair["stats"]["total_pnl"] = round(pair["stats"]["total_pnl"] + pnl, 6)

    pair.setdefault("equity_history", []).append({
        "t": _now(),
        "v": pair["stats"]["total_pnl"],
    })
    pair["equity_history"] = pair["equity_history"][-200:]

    pair.setdefault("closed_trades", []).append(closed)
    pair["closed_trades"] = pair["closed_trades"][-20:]

    state["trade_history"].append({
        "timestamp": _now(),
        "symbol":    symbol,
        "side":      "SELL",
        "price":     price,
        "quantity":  quantity,
        "reason":    reason,
        "pnl":       round(pnl, 6),
    })
    state["trade_history"] = state["trade_history"][-500:]
    return closed


def record_lesson(state: dict[str, Any], symbol: str, lesson: str, max_lessons: int = 10) -> None:
    pair = ensure_pair(state, symbol)
    lesson = lesson.strip()
    if not lesson:
        return
    pair.setdefault("lessons_learned", []).append({
        "t": _now(),
        "lesson": lesson,
    })
    pair["lessons_learned"] = pair["lessons_learned"][-max_lessons:]


def total_pnl(state: dict[str, Any]) -> float:
    return sum(p["stats"]["total_pnl"] for p in state["pairs"].values())
