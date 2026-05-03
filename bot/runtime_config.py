"""
Runtime config overlay.

Wraps config.py values but allows overriding them at runtime via Telegram
commands without restarting the server.  Changes are in-memory only and
are lost on restart; persist them to .env if you want them permanent.
"""
import config as _base

# Parameters that can be changed at runtime and their expected Python types.
_PARAM_TYPES: dict[str, type] = {
    "AI_CONFIDENCE_THRESHOLD": str,
    "AI_HOLD_CHECK_INTERVAL":  int,
    "BLACKOUT_END":            int,
    "BLACKOUT_START":          int,
    "FEAR_GREED_ENABLED":      bool,
    "FEAR_GREED_MAX":          int,
    "FEAR_GREED_MIN":          int,
    "MAX_OPEN_TRADES":         int,
    "RE_ENTRY_COOLDOWN":       int,
    "RE_ENTRY_PRICE_BUFFER":   float,
    "RISK_PER_TRADE":          float,
    "STOP_LOSS_PCT":           float,
    "TAKE_PROFIT_PCT":         float,
    "TRAILING_ACTIVATE_PCT":   float,
    "TRAILING_DISTANCE_PCT":   float,
    "TRAILING_STOP_ENABLED":   bool,
    "VOLUME_FILTER_ENABLED":   bool,
    "VOLUME_FILTER_MULT":      float,
    "VWAP_FILTER_ENABLED":     bool,
    "TRADING_BLACKOUT_ENABLED": bool,
}

_STR_CHOICES: dict[str, tuple[str, ...]] = {
    "AI_CONFIDENCE_THRESHOLD": ("LOW", "MEDIUM", "HIGH"),
}

_overrides: dict[str, object] = {}


def get(key: str) -> object:
    """Return the current value — runtime override beats .env."""
    return _overrides.get(key, getattr(_base, key))


def set_override(key: str, raw_value: str) -> tuple[bool, str]:
    """Parse and validate *raw_value* for *key*, then store the override.

    Returns (success, human-readable message).
    """
    k = key.upper()
    if k not in _PARAM_TYPES:
        valid = "\n".join(f"  • {p}" for p in sorted(_PARAM_TYPES))
        return False, f"Parámetro desconocido: `{key}`\n\nVálidos:\n{valid}"

    typ = _PARAM_TYPES[k]
    try:
        if typ is bool:
            lv = raw_value.lower()
            if lv in ("true", "1", "yes", "si", "sí", "on"):
                value: object = True
            elif lv in ("false", "0", "no", "off"):
                value = False
            else:
                return False, "Para booleanos usa: `true` / `false` (o `on`/`off`, `1`/`0`)"
        elif typ is str:
            value = raw_value.upper()
        else:
            value = typ(raw_value)
    except (ValueError, TypeError):
        return False, f"Valor inválido `{raw_value}` para `{k}` (esperado: {typ.__name__})"

    # Semantic validation
    if k in _STR_CHOICES and value not in _STR_CHOICES[k]:
        opts = " | ".join(_STR_CHOICES[k])
        return False, f"`{k}` debe ser uno de: {opts}"
    if k == "MAX_OPEN_TRADES" and int(value) < 1:  # type: ignore[arg-type]
        return False, "`MAX_OPEN_TRADES` debe ser ≥ 1"
    if k in {"RISK_PER_TRADE", "TAKE_PROFIT_PCT", "STOP_LOSS_PCT",
              "TRAILING_ACTIVATE_PCT", "TRAILING_DISTANCE_PCT"}:
        if not 0 < float(value) < 1:  # type: ignore[arg-type]
            return False, f"`{k}` debe estar entre 0 y 1 (ej: 0.006 = 0.6%)"
    if k in {"FEAR_GREED_MIN", "FEAR_GREED_MAX"}:
        if not 0 <= int(value) <= 100:  # type: ignore[arg-type]
            return False, f"`{k}` debe estar entre 0 y 100"

    _overrides[k] = value
    return True, f"✅ `{k}` = `{value}`"


def all_values() -> dict[str, object]:
    """All configurable parameters with their current effective values."""
    return {k: get(k) for k in sorted(_PARAM_TYPES)}


def active_overrides() -> dict[str, object]:
    """Only the parameters that have been changed at runtime."""
    return dict(_overrides)
