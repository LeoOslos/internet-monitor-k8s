# Internet Monitor

Monitor de calidad de conexión a internet. Mide latencia, jitter y packet loss cada 30 segundos contra múltiples targets, detecta cortes y expone un dashboard web en tiempo real.

**Dos formas de ejecutarlo:**

| | Docker Compose | Kubernetes |
|---|---|---|
| **Para quién** | Uso personal o doméstico | Infraestructura o producción |
| **Requisito** | Docker instalado | Cluster Kubernetes (k3s, etc.) |
| **Complejidad** | Mínima — tres comandos | Requiere conocimientos de K8s |
| **Persistencia** | Volúmenes Docker | PersistentVolume en el nodo |

---

## Inicio rápido con Docker Compose

> Esta es la opción recomendada si solo querés monitorear tu conexión en una PC o servidor con Docker instalado, sin necesidad de Kubernetes.

### Paso 1 — Descargá el proyecto

```bash
git clone https://github.com/LeoOslos/internet-monitor-k8s.git
cd internet-monitor-k8s
```

### Paso 2 — Levantá los servicios

```bash
docker compose up -d
```

Este comando construye la imagen y arranca el monitor y el dashboard en segundo plano. La primera vez tarda unos minutos mientras descarga las dependencias.

### Paso 3 — Abrí el dashboard

Abrí tu navegador y entrá a:

```
http://localhost:8765
```

Listo. El monitor empieza a registrar datos de inmediato y el dashboard se actualiza solo cada 30 segundos.

---

**Para detenerlo:**

```bash
docker compose down
```

Los datos quedan guardados en volúmenes Docker y se recuperan la próxima vez que hagas `docker compose up -d`.

**Para ver los logs en tiempo real:**

```bash
docker compose logs -f monitor
```

**Para cambiar la configuración** (nombre del lugar, IPs a monitorear, etc.) editá las variables de entorno en `docker-compose.yml` y reiniciá con `docker compose up -d`.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────┐
│                   Kubernetes (k3s)                  │
│                                                     │
│  ┌──────────────────┐       ┌─────────────────────┐ │
│  │  Pod: monitor    │       │  Pod: dashboard     │ │
│  │  monitor-        │       │  dashboard-         │ │
│  │  internet.py     │       │  internet.py        │ │
│  │                  │       │                     │ │
│  │  Ping c/ 30s a   │       │  HTTP server        │ │
│  │  8.8.8.8         │       │  puerto 8765        │ │
│  │  1.1.1.1         │       │                     │ │
│  │  8.8.4.4         │       │  NodePort 30765     │ │
│  └────────┬─────────┘       └──────────┬──────────┘ │
│           │                            │             │
│           └──────────┬─────────────────┘             │
│                      │ PersistentVolumeClaim          │
│                      │                               │
│          ┌───────────▼───────────┐                   │
│          │  PersistentVolume     │                   │
│          │  hostPath:            │                   │
│          │  ./storage/           │                   │
│          │  ├── data/            │                   │
│          │  │   └── monitor.db   │                   │
│          │  ├── logs/            │                   │
│          │  └── exports/         │                   │
│          └───────────────────────┘                   │
└─────────────────────────────────────────────────────┘
```

En Docker Compose la estructura es equivalente pero usando volúmenes Docker nombrados (`monitor_data`, `monitor_logs`, `monitor_exports`) en lugar de un PersistentVolume.

---

## Componentes

### Servicios

| Servicio | Imagen | Descripción |
|----------|--------|-------------|
| `monitor` | `internet-monitor:latest` | Loop de monitoreo — hace ping, guarda resultados en SQLite y detecta cortes |
| `dashboard` | `internet-monitor:latest` | Servidor HTTP que lee la DB y expone el dashboard en el puerto 8765 |

Ambos servicios usan la misma imagen Docker. El dashboard sobreescribe el `CMD` del Dockerfile para ejecutar `dashboard-internet.py` en lugar de `monitor-internet.py`.

### Almacenamiento

| Recurso | Tipo | Descripción |
|---------|------|-------------|
| `internet-monitor-pv` *(K8s)* | PersistentVolume | Volumen hostPath en `./storage/` del nodo |
| `internet-monitor-pvc` *(K8s)* | PersistentVolumeClaim | Claim de 1Gi montado por ambos pods |
| `monitor_data` *(Compose)* | Volumen Docker | Base de datos SQLite compartida entre monitor y dashboard |
| `monitor_logs` *(Compose)* | Volumen Docker | Logs del proceso de monitoreo |
| `monitor_exports` *(Compose)* | Volumen Docker | CSVs exportados diariamente |

Estructura de datos:

```
data/
└── monitor.db              # Base de datos SQLite (WAL mode)
logs/
└── monitor.log             # Log del proceso de monitoreo
exports/
├── internet_YYYY-MM-DD.csv # Muestras de ping del día
└── cortes_YYYY-MM-DD.csv   # Cortes detectados en el día
```

### Configuración

Variables de entorno disponibles:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `LOCATION_NAME` | `Casa` | Nombre del nodo de monitoreo |
| `PING_TARGETS` | `8.8.8.8,1.1.1.1,8.8.4.4` | IPs a monitorear (separadas por coma) |
| `CHECK_INTERVAL_S` | `30` | Intervalo entre chequeos en segundos |
| `DASHBOARD_PORT` | `8765` | Puerto del servidor HTTP del dashboard |
| `DB_PATH` | `/app/data/monitor.db` | Path de la base de datos SQLite |
| `LOG_DIR` | `/app/logs` | Directorio de logs |
| `CSV_EXPORT_DIR` | `/app/exports` | Directorio de exportaciones CSV |
| `EMAIL_ENABLED` | `false` | Activa notificaciones por email al recuperarse la conexión |
| `EMAIL_FROM` | — | Cuenta Gmail de origen |
| `EMAIL_TO` | — | Destinatario de las notificaciones |
| `EMAIL_APP_PASSWORD` | — | App Password de Gmail |

---

## Base de datos

SQLite con tres tablas:

- **`ping_samples`** — Una fila por ping por target. Registra latencia, jitter, packet loss y si fue exitoso.
- **`outages`** — Un registro por corte detectado, con timestamp de inicio, fin y duración en segundos.
- **`daily_summaries`** — Resumen agregado por día: disponibilidad, latencia promedio/máxima, jitter, packet loss y totales de cortes.

---

## Despliegue en Kubernetes (avanzado)

> Usá esta opción si tenés un cluster Kubernetes y querés aprovechar su orquestación, reinicio automático de pods y gestión de volúmenes persistentes.

### Manifests

```
k8s/
├── configmap.yaml             # ConfigMap con variables de entorno
├── secret.yaml                # Secret con credenciales de email
├── persistent-volume.yaml     # PersistentVolume + PersistentVolumeClaim
├── deployment.yaml            # Deployment del monitor
├── dashboard-deployment.yaml  # Deployment del dashboard
└── dashboard-service.yaml     # Service NodePort para el dashboard
```

### 1. Construir e importar la imagen

```bash
docker build -t internet-monitor:latest .
docker save internet-monitor:latest | sudo k3s ctr images import -
```

### 2. Aplicar los manifests

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/persistent-volume.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/dashboard-deployment.yaml
kubectl apply -f k8s/dashboard-service.yaml
```

### 3. Verificar el estado

```bash
kubectl get pods -l app=internet-monitor
kubectl get pods -l app=internet-monitor-dashboard
kubectl get pvc internet-monitor-pvc
```

### 4. Acceder al dashboard

```
http://<IP-del-nodo>:30765
```

---

## Dashboard

El dashboard se actualiza automáticamente cada 30 segundos y muestra:

- Estado actual de la conexión (online / offline)
- Health score calculado en base a disponibilidad, packet loss, jitter y latencia
- KPIs del día: disponibilidad, latencia promedio/máxima, jitter, packet loss y cortes
- Gráfico de latencia de las últimas 2 horas
- Tabla de últimos cortes con duración
- Historial diario

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /` | Dashboard HTML |
| `GET /api/status` | Estado actual + últimos pings + corte activo |
| `GET /api/history?days=7` | Resumen de los últimos N días |
| `GET /api/outages` | Lista de cortes registrados |
