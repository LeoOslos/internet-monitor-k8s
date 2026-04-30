"""
Configuración del Internet Monitor.
Los secretos se leen del archivo .env (nunca compartir ese archivo).
"""

import os
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    "location_name": "Casa",

    "ping_targets": [
        "8.8.8.8",   # Google DNS
        "1.1.1.1",   # Cloudflare DNS
        "8.8.4.4",   # Google DNS secundario
    ],

    "check_interval_s": 30,

    "db_path":        "/home/leoadmin/internet-monitor/data/monitor.db",
    "log_dir":        "/home/leoadmin/internet-monitor/logs",
    "csv_export_dir": "/home/leoadmin/internet-monitor/exports",

    "dashboard_port": 8765,

    "email": {
        "enabled":      False,  # ← cambiar a True cuando cargues las credenciales en .env
        "from":         os.getenv("EMAIL_FROM", ""),
        "to":           os.getenv("EMAIL_TO", ""),
        "app_password": os.getenv("EMAIL_APP_PASSWORD", ""),
    },
}