#!/usr/bin/env python3
"""
Internet Monitor — Dashboard HTTP
"""

import sqlite3
import json
import os
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from config import CONFIG

DB_PATH = CONFIG["db_path"]
PORT    = CONFIG["dashboard_port"]


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def api_status():
    con = get_db()

    latest = con.execute("""
        SELECT target, latency_ms, jitter_ms, packet_loss, success, ts
        FROM ping_samples
        WHERE id IN (SELECT MAX(id) FROM ping_samples GROUP BY target)
        ORDER BY target
    """).fetchall()

    active_outage = con.execute("""
        SELECT id, start_ts FROM outages
        WHERE end_ts IS NULL ORDER BY id DESC LIMIT 1
    """).fetchone()

    today = datetime.now().strftime("%Y-%m-%d")
    summary = con.execute(
        "SELECT * FROM daily_summaries WHERE date=?", (today,)
    ).fetchone()

    recent_outages = con.execute("""
        SELECT id, start_ts, end_ts, duration_s
        FROM outages ORDER BY id DESC LIMIT 5
    """).fetchall()

    two_hours_ago  = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    main_target    = CONFIG["ping_targets"][0]
    latency_series = con.execute("""
        SELECT strftime('%H:%M', ts) as minute,
               ROUND(AVG(latency_ms), 1)   as avg_lat,
               ROUND(AVG(jitter_ms), 1)    as avg_jitter,
               ROUND(AVG(packet_loss), 1)  as avg_loss,
               SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failures
        FROM ping_samples
        WHERE ts >= ? AND target=?
        GROUP BY strftime('%Y-%m-%d %H:%M', ts)
        ORDER BY minute
    """, (two_hours_ago, main_target)).fetchall()

    con.close()
    is_connected = not active_outage and any(r["success"] for r in latest)

    return {
        "status":         "online" if is_connected else "offline",
        "active_outage":  dict(active_outage) if active_outage else None,
        "targets":        [dict(r) for r in latest],
        "today":          dict(summary) if summary else {},
        "recent_outages": [dict(r) for r in recent_outages],
        "latency_series": [dict(r) for r in latency_series],
        "server_time":    datetime.now().isoformat(timespec="seconds"),
    }


def api_history(days=7):
    con = get_db()
    rows = con.execute("""
        SELECT date, total_checks, failed_checks, avg_latency_ms,
               max_latency_ms, avg_jitter_ms, avg_packet_loss,
               outage_count, total_outage_s
        FROM daily_summaries ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def api_outages(limit=50):
    con = get_db()
    rows = con.execute("""
        SELECT id, start_ts, end_ts, duration_s
        FROM outages ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Monitor de Internet</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  header { background: #1e293b; padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem; border-bottom: 1px solid #334155; }
  header h1 { font-size: 1.2rem; font-weight: 600; }
  .dot { width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }
  .online  { background: #22c55e; box-shadow: 0 0 8px #22c55e88; animation: pulse 2s infinite; }
  .offline { background: #ef4444; box-shadow: 0 0 8px #ef444488; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
  .badge { padding: .2rem .7rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }
  .badge-green { background: #15803d; color: #bbf7d0; }
  .badge-red   { background: #991b1b; color: #fecaca; }
  main { max-width: 1100px; margin: 0 auto; padding: 1.5rem; display: grid; gap: 1.5rem; }
  .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
  .grid-4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; }
  .card h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; color: #94a3b8; margin-bottom: .8rem; }
  .big { font-size: 2rem; font-weight: 700; }
  .sub { font-size: .8rem; color: #64748b; margin-top: .2rem; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th { text-align: left; color: #64748b; font-weight: 500; padding: .4rem .6rem; border-bottom: 1px solid #334155; }
  td { padding: .5rem .6rem; border-bottom: 1px solid #1e293b; }
  tr:last-child td { border-bottom: none; }
  .chart { height: 140px; display: flex; align-items: flex-end; gap: 2px; overflow: hidden; }
  .bar { flex: 1; min-width: 4px; border-radius: 3px 3px 0 0; }
  .outage-card { background: #450a0a; border-color: #991b1b; }
  .green  { color: #22c55e; }
  .yellow { color: #f59e0b; }
  .red    { color: #ef4444; }
  .muted  { color: #64748b; }

  /* Health score */
  .score-wrap { display: flex; align-items: center; gap: 1rem; }
  .score-num  { font-size: 2.8rem; font-weight: 800; }
  .score-bar-bg { flex: 1; height: 10px; background: #1e3a2a; border-radius: 999px; overflow: hidden; }
  .score-bar    { height: 100%; border-radius: 999px; transition: width .5s; }
</style>
</head>
<body>

<header>
  <div class="dot" id="dot"></div>
  <h1>Monitor de Internet</h1>
  <span class="badge" id="badge"></span>
  <span style="margin-left:auto;font-size:.8rem;color:#475569">
    Actualiza cada 30s &mdash; <span id="srv-time"></span>
  </span>
</header>

<main>
  <div class="card outage-card" id="outage-card" style="display:none">
    <h2>⚠️ Corte en curso</h2>
    <div id="outage-info" style="font-size:.95rem;line-height:1.9"></div>
  </div>

  <!-- Health score -->
  <div class="card">
    <h2>Health Score</h2>
    <div class="score-wrap">
      <div class="score-num" id="score">—</div>
      <div style="flex:1">
        <div class="score-bar-bg">
          <div class="score-bar" id="score-bar" style="width:0%;background:#22c55e"></div>
        </div>
        <div class="sub" id="score-detail" style="margin-top:.5rem"></div>
      </div>
    </div>
  </div>

  <div class="grid-4">
    <div class="card">
      <h2>Disponibilidad hoy</h2>
      <div class="big" id="avail">—</div>
      <div class="sub" id="checks"></div>
    </div>
    <div class="card">
      <h2>Latencia promedio</h2>
      <div class="big" id="avg-lat">—</div>
      <div class="sub" id="max-lat"></div>
    </div>
    <div class="card">
      <h2>Jitter promedio</h2>
      <div class="big" id="avg-jitter">—</div>
      <div class="sub">ideal &lt;5 ms</div>
    </div>
    <div class="card">
      <h2>Packet Loss</h2>
      <div class="big" id="avg-loss">—</div>
      <div class="sub">ideal &lt;0.1%</div>
    </div>
    <div class="card">
      <h2>Cortes hoy</h2>
      <div class="big" id="outage-count">—</div>
      <div class="sub" id="outage-total"></div>
    </div>
    <div class="card">
      <h2>Targets</h2>
      <div id="targets"></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <h2>Latencia últimas 2 horas</h2>
      <div class="chart" id="chart"></div>
    </div>
    <div class="card">
      <h2>Últimos cortes</h2>
      <table>
        <thead><tr><th>Inicio</th><th>Fin</th><th>Duración</th></tr></thead>
        <tbody id="outages-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Historial diario</h2>
    <table>
      <thead>
        <tr>
          <th>Fecha</th><th>Disponibilidad</th><th>Lat. prom.</th>
          <th>Jitter</th><th>Packet Loss</th><th>Cortes</th><th>Sin internet</th>
        </tr>
      </thead>
      <tbody id="history-tbody"></tbody>
    </table>
  </div>
</main>

<script>
const fmtDur = s => {
  if (!s) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
  return h ? `${h}h ${m}m ${sec}s` : m ? `${m}m ${sec}s` : `${sec}s`;
};
const fmtTs  = ts  => ts ? ts.replace('T', ' ') : '—';
const pct    = (ok, total) => total ? ((ok/total)*100).toFixed(1)+'%' : '—';
const fmt1   = v  => v != null ? v.toFixed(1) : '—';

function calcScore(avail, loss, jitter, lat95) {
  if (avail == null) return null;
  const a = parseFloat(avail);
  const scoreAvail  = Math.max(0, (a - 95) / 5 * 40);          // 40%
  const scoreLoss   = loss  != null ? Math.max(0, (1 - loss/2)  * 25) : 25; // 25%
  const scoreJitter = jitter!= null ? Math.max(0, (1 - jitter/30)* 20) : 20; // 20%
  const scoreLat    = lat95 != null ? Math.max(0, (1 - lat95/200)* 15) : 15; // 15%
  return Math.round(scoreAvail + scoreLoss + scoreJitter + scoreLat);
}

function scoreColor(s) {
  return s >= 80 ? '#22c55e' : s >= 60 ? '#f59e0b' : '#ef4444';
}

function scoreLabel(s) {
  return s >= 80 ? '🟢 Excelente' : s >= 60 ? '🟡 Degradado' : '🔴 Crítico';
}

async function load() {
  const [st, hist] = await Promise.all([
    fetch('/api/status').then(r => r.json()),
    fetch('/api/history').then(r => r.json()),
  ]);

  // Header
  document.getElementById('dot').className     = 'dot ' + st.status;
  document.getElementById('badge').textContent = st.status === 'online' ? 'En línea' : 'SIN INTERNET';
  document.getElementById('badge').className   = 'badge ' + (st.status === 'online' ? 'badge-green' : 'badge-red');
  document.getElementById('srv-time').textContent = fmtTs(st.server_time);

  // Corte activo
  if (st.active_outage) {
    const dur = Math.round((Date.now() - new Date(st.active_outage.start_ts)) / 1000);
    document.getElementById('outage-card').style.display = '';
    document.getElementById('outage-info').innerHTML =
      `<b>Inicio:</b> ${fmtTs(st.active_outage.start_ts)}<br>` +
      `<b>Duración hasta ahora:</b> ${fmtDur(dur)}`;
  }

  // KPIs
  const t = st.today;
  let availPct = null;
  if (t && t.total_checks) {
    const ok = t.total_checks - (t.failed_checks || 0);
    availPct = (ok / t.total_checks) * 100;
    document.getElementById('avail').textContent   = availPct.toFixed(1) + '%';
    document.getElementById('checks').textContent  = `${ok}/${t.total_checks} checks`;
    document.getElementById('avg-lat').textContent = fmt1(t.avg_latency_ms) + ' ms';
    document.getElementById('max-lat').textContent = t.max_latency_ms ? `Máx: ${fmt1(t.max_latency_ms)} ms` : '';

    const jitter = t.avg_jitter_ms;
    const jEl = document.getElementById('avg-jitter');
    jEl.textContent = fmt1(jitter) + ' ms';
    jEl.className = 'big ' + (jitter == null ? '' : jitter < 5 ? 'green' : jitter < 15 ? 'yellow' : 'red');

    const loss = t.avg_packet_loss;
    const lEl = document.getElementById('avg-loss');
    lEl.textContent = fmt1(loss) + '%';
    lEl.className = 'big ' + (loss == null ? '' : loss < 0.1 ? 'green' : loss < 2 ? 'yellow' : 'red');

    document.getElementById('outage-count').textContent = t.outage_count ?? '0';
    document.getElementById('outage-total').textContent = t.total_outage_s ? fmtDur(t.total_outage_s) : 'Sin cortes';
  }

  // Health score
  const score = calcScore(availPct, t.avg_packet_loss, t.avg_jitter_ms, null);
  if (score != null) {
    const col = scoreColor(score);
    document.getElementById('score').textContent     = score;
    document.getElementById('score').style.color     = col;
    document.getElementById('score-bar').style.width = score + '%';
    document.getElementById('score-bar').style.background = col;
    document.getElementById('score-detail').textContent   = scoreLabel(score);
  }

  // Targets
  document.getElementById('targets').innerHTML = (st.targets || []).map(t =>
    `<div style="display:flex;justify-content:space-between;margin-bottom:.4rem;font-size:.85rem">
      <span>${t.target}</span>
      <span class="${t.success ? 'green' : 'red'}">
        ${t.success ? (t.latency_ms ? fmt1(t.latency_ms)+' ms' : 'OK') : 'FALLO'}
      </span>
    </div>`
  ).join('');

  // Gráfico latencia
  const series = st.latency_series || [];
  if (series.length) {
    const max = Math.max(...series.map(s => s.avg_lat || 0), 1);
    document.getElementById('chart').innerHTML = series.map(s => {
      const h     = s.avg_lat ? Math.max(4, (s.avg_lat / max) * 100) : 4;
      const color = s.failures > 0 ? '#ef4444'
                  : (s.avg_loss > 1 || s.avg_jitter > 15) ? '#f59e0b'
                  : '#22c55e';
      return `<div class="bar" style="height:${h}%;background:${color}"
                   title="${s.minute} — lat: ${s.avg_lat} ms | jitter: ${s.avg_jitter} ms | loss: ${s.avg_loss}%"></div>`;
    }).join('');
  }

  // Últimos cortes
  document.getElementById('outages-tbody').innerHTML =
    (st.recent_outages || []).map(o =>
      `<tr>
        <td>${fmtTs(o.start_ts)}</td>
        <td>${o.end_ts ? fmtTs(o.end_ts) : '<span class="red">En curso</span>'}</td>
        <td>${fmtDur(o.duration_s)}</td>
      </tr>`
    ).join('') || '<tr><td colspan="3" class="muted">Sin cortes registrados</td></tr>';

  // Historial
  document.getElementById('history-tbody').innerHTML = hist.map(h => {
    const ok    = h.total_checks - (h.failed_checks || 0);
    const avail = pct(ok, h.total_checks);
    const color = parseFloat(avail) > 99 ? '#22c55e' : parseFloat(avail) > 95 ? '#f59e0b' : '#ef4444';
    const jColor = h.avg_jitter_ms == null ? '' : h.avg_jitter_ms < 5 ? 'color:#22c55e' : h.avg_jitter_ms < 15 ? 'color:#f59e0b' : 'color:#ef4444';
    const lColor = h.avg_packet_loss == null ? '' : h.avg_packet_loss < 0.1 ? 'color:#22c55e' : h.avg_packet_loss < 2 ? 'color:#f59e0b' : 'color:#ef4444';
    return `<tr>
      <td>${h.date}</td>
      <td style="color:${color};font-weight:600">${avail}</td>
      <td>${fmt1(h.avg_latency_ms)} ms</td>
      <td style="${jColor}">${fmt1(h.avg_jitter_ms)} ms</td>
      <td style="${lColor}">${fmt1(h.avg_packet_loss)}%</td>
      <td>${h.outage_count ?? 0}</td>
      <td>${fmtDur(h.total_outage_s)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" class="muted">Sin datos aún</td></tr>';
}

load().catch(console.error);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not os.path.exists(DB_PATH):
            self.send_error(503, "Base de datos no disponible aún")
            return
        try:
            if self.path in ("/", "/index.html"):
                self.send_html(HTML)
            elif self.path == "/api/status":
                self.send_json(api_status())
            elif self.path.startswith("/api/history"):
                days = 7
                if "days=" in self.path:
                    try: days = int(self.path.split("days=")[1].split("&")[0])
                    except: pass
                self.send_json(api_history(days))
            elif self.path == "/api/outages":
                self.send_json(api_outages())
            else:
                self.send_error(404)
        except Exception as e:
            self.send_error(500, str(e))


def main():
    print(f"Dashboard corriendo en http://0.0.0.0:{PORT}")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.serve_forever()


if __name__ == "__main__":
    main()