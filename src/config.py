"""
Configuración del Internet Monitor.
En Kubernetes los valores vienen de ConfigMap y Secret como variables de entorno.
En desarrollo local siguen funcionando desde el archivo .env
"""
import os
from dotenv import load_dotenv

# En desarrollo local carga el .env, en Kubernetes no hay .env y no pasa nada
load_dotenv()

CONFIG = {
    "location_name":  os.getenv("LOCATION_NAME", "Casa"),
    "ping_targets":   os.getenv("PING_TARGETS", "8.8.8.8,1.1.1.1,8.8.4.4").split(","),
    "check_interval_s": int(os.getenv("CHECK_INTERVAL_S", "30")),
    "db_path":        os.getenv("DB_PATH", "./data/monitor.db"),
    "log_dir":        os.getenv("LOG_DIR", "./logs"),
    "csv_export_dir": os.getenv("CSV_EXPORT_DIR", "./exports"),
    "dashboard_port": int(os.getenv("DASHBOARD_PORT", "8765")),
    "email": {
        "enabled":      os.getenv("EMAIL_ENABLED", "false").lower() == "true",
        "from":         os.getenv("EMAIL_FROM", ""),
        "to":           os.getenv("EMAIL_TO", ""),
        "app_password": os.getenv("EMAIL_APP_PASSWORD", ""),
    },
}
