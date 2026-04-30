#!/usr/bin/env python3
"""
Internet Connection Quality Monitor
Monitorea la calidad de conexión, detecta cortes y mide latencia/packet loss/jitter.
Email solo al recuperarse la conexión, con el resumen completo del corte.
"""

import sqlite3
import subprocess
import time
import datetime
import smtplib
import csv
import os
import re
import logging
import signal
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import CONFIG

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(CONFIG["log_dir"], exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(CONFIG["log_dir"], "monitor.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── Base de datos ─────────────────────────────────────────────────────────────
def init_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS ping_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            target      TEXT    NOT NULL,
            latency_ms  REAL,
            success     INTEGER NOT NULL,
            jitter_ms   REAL,
            packet_loss REAL
        );

        CREATE TABLE IF NOT EXISTS outages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts    TEXT NOT NULL,
            end_ts      TEXT,
            duration_s  INTEGER
        );

        CREATE TABLE IF NOT EXISTS daily_summaries (
            date            TEXT PRIMARY KEY,
            total_checks    INTEGER,
            failed_checks   INTEGER,
            avg_latency_ms  REAL,
            max_latency_ms  REAL,
            avg_jitter_ms   REAL,
            avg_packet_loss REAL,
            outage_count    INTEGER,
            total_outage_s  INTEGER,
            exported_csv    INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_ping_ts      ON ping_samples(ts);
        CREATE INDEX IF NOT EXISTS idx_outage_start ON outages(start_ts);
    """)
    # Migraciones por si la BD ya existe
    
    return con


# ── Ping ──────────────────────────────────────────────────────────────────────
def ping_host(host, count=3, timeout=5):
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), "-q", host],
            capture_output=True, text=True, timeout=timeout * count + 5
        )
        avg    = None
        jitter = None
        loss   = None

        for line in result.stdout.splitlines():
            # Packet loss: "3 packets transmitted, 2 received, 33% packet loss"
            if "packet loss" in line:
                m = re.search(r"(\d+(?:\.\d+)?)% packet loss", line)
                if m:
                    loss = float(m.group(1))
            # Latencia y jitter: "rtt min/avg/max/mdev = 12.1/14.5/16.7/1.8 ms"
            if "rtt" in line or "round-trip" in line:
                parts  = line.split("=")[1].strip().split("/")
                avg    = float(parts[1])
                jitter = float(parts[3].split()[0])

        success = result.returncode == 0
        return success, avg, jitter, loss

    except Exception as e:
        log.debug(f"ping {host} error: {e}")
        return False, None, None, None


def check_connectivity(targets):
    results = []
    for target in targets:
        ok, latency, jitter, loss = ping_host(target)
        results.append({
            "target":     target,
            "success":    ok,
            "latency_ms": latency,
            "jitter_ms":  jitter,
            "loss_pct":   loss,
        })
    is_connected = any(r["success"] for r in results)
    return is_connected, results


# ── Email (solo al recuperarse) ───────────────────────────────────────────────
def send_email(subject, body):
    cfg = CONFIG["email"]
    if not cfg.get("enabled"):
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["from"]
        msg["To"]      = cfg["to"]
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(cfg["from"], cfg["app_password"])
            s.sendmail(cfg["from"], cfg["to"], msg.as_string())
        log.info(f"Email enviado: {subject}")
    except Exception as e:
        log.error(f"Error enviando email: {e}")


def email_outage_end(outage_id, start_ts, end_ts, duration_s):
    mins, secs = divmod(int(duration_s), 60)
    hrs,  mins = divmod(mins, 60)
    dur_str = f"{hrs}h {mins}m {secs}s" if hrs else f"{mins}m {secs}s"
    body = f"""
    <h2 style="color:#27ae60;">✅ Conexión restaurada</h2>
    <table style="font-family:monospace;border-collapse:collapse">
      <tr><td style="padding:.3rem 1rem .3rem 0"><b>Inicio del corte:</b></td><td>{start_ts}</td></tr>
      <tr><td style="padding:.3rem 1rem .3rem 0"><b>Restauración:</b></td>   <td>{end_ts}</td></tr>
      <tr><td style="padding:.3rem 1rem .3rem 0"><b>Duración:</b></td>       <td>{dur_str}</td></tr>
      <tr><td style="padding:.3rem 1rem .3rem 0"><b>ID de evento:</b></td>   <td>{outage_id}</td></tr>
    </table>
    <hr><small>Internet Monitor — {CONFIG['location_name']}</small>
    """
    send_email(f"[Internet] ✅ Conexión restaurada — duración: {dur_str}", body)


# ── CSV Export ────────────────────────────────────────────────────────────────
def export_daily_csv(con, date_str):
    export_dir = CONFIG["csv_export_dir"]
    os.makedirs(export_dir, exist_ok=True)

    rows = con.execute("""
        SELECT ts, target, latency_ms, jitter_ms, packet_loss, success
        FROM ping_samples WHERE ts LIKE ? ORDER BY ts
    """, (f"{date_str}%",)).fetchall()

    path = os.path.join(export_dir, f"internet_{date_str}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Timestamp", "Destino", "Latencia (ms)", "Jitter (ms)", "Packet Loss (%)", "Exitoso"])
        w.writerows(rows)

    outages = con.execute("""
        SELECT id, start_ts, end_ts, duration_s FROM outages
        WHERE start_ts LIKE ? OR end_ts LIKE ? ORDER BY start_ts
    """, (f"{date_str}%", f"{date_str}%")).fetchall()

    outage_path = os.path.join(export_dir, f"cortes_{date_str}.csv")
    with open(outage_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Inicio corte", "Fin corte", "Duración (seg)"])
        w.writerows(outages)

    log.info(f"CSV exportado: {path}")
    con.execute("UPDATE daily_summaries SET exported_csv=1 WHERE date=?", (date_str,))
    con.commit()


# ── Resumen diario ────────────────────────────────────────────────────────────
def update_daily_summary(con, date_str):
    row = con.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),
               AVG(CASE WHEN success=1 THEN latency_ms END),
               MAX(CASE WHEN success=1 THEN latency_ms END),
               AVG(CASE WHEN success=1 THEN jitter_ms END),
               AVG(packet_loss)
        FROM ping_samples WHERE ts LIKE ?
    """, (f"{date_str}%",)).fetchone()

    outages = con.execute("""
        SELECT COUNT(*), COALESCE(SUM(duration_s), 0)
        FROM outages
        WHERE start_ts LIKE ? AND end_ts IS NOT NULL
    """, (f"{date_str}%",)).fetchone()

    con.execute("""
        INSERT INTO daily_summaries
            (date, total_checks, failed_checks, avg_latency_ms, max_latency_ms,
             avg_jitter_ms, avg_packet_loss, outage_count, total_outage_s)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            total_checks    = excluded.total_checks,
            failed_checks   = excluded.failed_checks,
            avg_latency_ms  = excluded.avg_latency_ms,
            max_latency_ms  = excluded.max_latency_ms,
            avg_jitter_ms   = excluded.avg_jitter_ms,
            avg_packet_loss = excluded.avg_packet_loss,
            outage_count    = excluded.outage_count,
            total_outage_s  = excluded.total_outage_s
    """, (date_str, row[0], row[1] or 0, row[2], row[3],
          row[4], row[5], outages[0] or 0, outages[1] or 0))
    con.commit()


# ── Loop principal ────────────────────────────────────────────────────────────
def main():
    log.info("=== Internet Monitor iniciado ===")
    con = init_db(CONFIG["db_path"])

    current_outage_id = None
    outage_start_ts   = None
    last_export_date  = None

    def shutdown(sig, frame):
        log.info("Cerrando monitor...")
        con.close()
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    targets  = CONFIG["ping_targets"]
    interval = CONFIG["check_interval_s"]

    while True:
        now      = datetime.datetime.now()
        ts       = now.isoformat(timespec="seconds")
        date_str = now.strftime("%Y-%m-%d")

        is_connected, results = check_connectivity(targets)

        for r in results:
            con.execute(
                """INSERT INTO ping_samples
                   (ts, target, latency_ms, success, jitter_ms, packet_loss)
                   VALUES (?,?,?,?,?,?)""",
                (ts, r["target"], r["latency_ms"], 1 if r["success"] else 0,
                 r["jitter_ms"], r["loss_pct"])
            )
        con.commit()

        if not is_connected:
            if current_outage_id is None:
                cur = con.execute("INSERT INTO outages (start_ts) VALUES (?)", (ts,))
                current_outage_id = cur.lastrowid
                outage_start_ts   = ts
                con.commit()
                log.warning(f"CORTE DETECTADO — ID {current_outage_id} — {ts}")
            else:
                log.debug(f"Corte en curso (ID {current_outage_id})")
        else:
            if current_outage_id is not None:
                start_dt   = datetime.datetime.fromisoformat(outage_start_ts)
                duration_s = (now - start_dt).total_seconds()
                con.execute("""
                    UPDATE outages SET end_ts=?, duration_s=? WHERE id=?
                """, (ts, int(duration_s), current_outage_id))
                con.commit()
                log.info(f"Conexión restaurada — ID {current_outage_id} — {duration_s:.0f}s")
                email_outage_end(current_outage_id, outage_start_ts, ts, duration_s)
                current_outage_id = None
                outage_start_ts   = None

        if last_export_date and last_export_date != date_str:
            update_daily_summary(con, last_export_date)
            export_daily_csv(con, last_export_date)

        last_export_date = date_str
        update_daily_summary(con, date_str)

        log.info(f"Ciclo completado, durmiendo {interval}s")
        time.sleep(interval)


if __name__ == "__main__":
    main()