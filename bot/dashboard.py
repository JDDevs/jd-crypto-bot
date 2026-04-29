"""
Lightweight Flask dashboard. Reads state.json on every request and
renders a single auto-refreshing HTML page with per-pair status,
last AI decision, open trades and a recent trade history table.
"""
import logging
from flask import Flask, jsonify, render_template_string
from bot import state as state_mod

log = logging.getLogger(__name__)

app = Flask(__name__)
# Quiet werkzeug request logs
logging.getLogger("werkzeug").setLevel(logging.WARNING)


_PAGE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>JD Crypto Bot</title>
<style>
  body { font-family: 'Segoe UI', Tahoma, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }
  h1 { margin-top: 0; color:#38bdf8; }
  h2 { color:#94a3b8; margin-top: 32px; border-bottom: 1px solid #1e293b; padding-bottom: 8px; }
  .pnl { font-size: 32px; font-weight: bold; }
  .pos { color: #22c55e; }
  .neg { color: #ef4444; }
  .neu { color: #94a3b8; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
  .card { background:#1e293b; border-radius:8px; padding:16px; }
  .card h3 { margin: 0 0 12px 0; color:#fbbf24; }
  .row { display:flex; justify-content:space-between; margin: 4px 0; }
  .label { color:#94a3b8; }
  .value { font-family: 'Consolas', monospace; }
  .signal { padding:2px 8px; border-radius:4px; font-weight:bold; font-size:12px; }
  .BUY { background:#16a34a; color:#fff; }
  .SELL { background:#dc2626; color:#fff; }
  .HOLD { background:#475569; color:#fff; }
  .open { background:#fbbf24; color:#0f172a; padding:2px 8px; border-radius:4px; font-size:12px; }
  table { width:100%; border-collapse:collapse; margin-top:8px; font-size:14px; }
  th, td { padding:6px 10px; text-align:left; border-bottom:1px solid #334155; }
  th { color:#94a3b8; font-weight:normal; }
  .reason { color:#94a3b8; font-style:italic; font-size:13px; margin-top: 8px; }
  .footer { margin-top: 32px; color:#475569; font-size:12px; }
</style>
</head>
<body>
  <h1>JD Crypto Bot Dashboard</h1>

  <div class="row">
    <div>
      <div class="label">Total PnL</div>
      <div class="pnl {{ 'pos' if total_pnl > 0 else ('neg' if total_pnl < 0 else 'neu') }}">
        {{ '%+.4f'|format(total_pnl) }} USDT
      </div>
    </div>
    <div>
      <div class="label">Pares activos</div>
      <div class="pnl neu">{{ pairs|length }}</div>
    </div>
    <div>
      <div class="label">Operaciones registradas</div>
      <div class="pnl neu">{{ history|length }}</div>
    </div>
  </div>

  <h2>Pares</h2>
  <div class="grid">
  {% for symbol, p in pairs.items() %}
    <div class="card">
      <h3>{{ symbol }}
        {% if p.open_trade %}<span class="open">EN POSICIÓN</span>{% endif %}
      </h3>

      {% if p.last_ai_signal %}
        <div class="row">
          <span class="label">Última señal IA</span>
          <span class="signal {{ p.last_ai_signal.decision }}">
            {{ p.last_ai_signal.decision }} ({{ p.last_ai_signal.confidence }})
          </span>
        </div>
        <div class="reason">"{{ p.last_ai_signal.reasoning }}"</div>
      {% else %}
        <div class="label">Aún sin análisis...</div>
      {% endif %}

      {% if p.open_trade %}
        <hr style="border-color:#334155; margin:12px 0;">
        <div class="row"><span class="label">Entrada</span>
          <span class="value">{{ '%.4f'|format(p.open_trade.entry_price) }}</span></div>
        <div class="row"><span class="label">Take Profit</span>
          <span class="value pos">{{ '%.4f'|format(p.open_trade.take_profit) }}</span></div>
        <div class="row"><span class="label">Stop Loss</span>
          <span class="value neg">{{ '%.4f'|format(p.open_trade.stop_loss) }}</span></div>
        <div class="row"><span class="label">Cantidad</span>
          <span class="value">{{ '%.6f'|format(p.open_trade.quantity) }}</span></div>
      {% endif %}

      <hr style="border-color:#334155; margin:12px 0;">
      <div class="row"><span class="label">Wins / Losses</span>
        <span class="value">
          <span class="pos">{{ p.stats.wins }}</span> / <span class="neg">{{ p.stats.losses }}</span>
        </span></div>
      <div class="row"><span class="label">PnL del par</span>
        <span class="value {{ 'pos' if p.stats.total_pnl > 0 else ('neg' if p.stats.total_pnl < 0 else 'neu') }}">
          {{ '%+.4f'|format(p.stats.total_pnl) }} USDT
        </span></div>
    </div>
  {% endfor %}
  </div>

  <h2>Historial reciente</h2>
  <table>
    <thead>
      <tr><th>Hora (UTC)</th><th>Par</th><th>Lado</th><th>Precio</th><th>Cantidad</th><th>PnL</th><th>Razón</th></tr>
    </thead>
    <tbody>
    {% for t in history %}
      <tr>
        <td>{{ t.timestamp }}</td>
        <td>{{ t.symbol }}</td>
        <td><span class="signal {{ t.side }}">{{ t.side }}</span></td>
        <td class="value">{{ '%.4f'|format(t.price) }}</td>
        <td class="value">{{ '%.6f'|format(t.quantity) }}</td>
        <td class="value {{ 'pos' if t.pnl and t.pnl > 0 else ('neg' if t.pnl and t.pnl < 0 else 'neu') }}">
          {% if t.pnl is not none %}{{ '%+.4f'|format(t.pnl) }}{% else %}—{% endif %}
        </td>
        <td class="reason">{{ t.reason }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="footer">Auto-refresh cada 5s · State file: state.json</div>
</body>
</html>
"""


@app.route("/")
def index():
    state = state_mod.load()
    history = list(reversed(state.get("trade_history", [])))[:20]
    return render_template_string(
        _PAGE,
        pairs=state.get("pairs", {}),
        history=history,
        total_pnl=state_mod.total_pnl(state),
    )


@app.route("/api/state")
def api_state():
    return jsonify(state_mod.load())


def run(host: str, port: int) -> None:
    log.info("Dashboard listening on http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)
