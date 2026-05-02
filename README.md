# Internet Monitor K8s

Monitor de calidad de conexión a internet desplegado en Kubernetes. Mide latencia, jitter y packet loss cada 30 segundos contra múltiples targets, detecta cortes y expone un dashboard web en tiempo real.

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

---

## Componentes

### Pods

| Pod | Imagen | Descripción |
|-----|--------|-------------|
| `internet-monitor` | `internet-monitor:latest` | Loop de monitoreo — hace ping, guarda resultados en SQLite y detecta cortes |
| `internet-monitor-dashboard` | `internet-monitor:latest` | Servidor HTTP que lee la DB y expone el dashboard en el puerto 8765 |

Ambos pods usan la misma imagen Docker. El dashboard sobreescribe el `CMD` del Dockerfile para ejecutar `dashboard-internet.py` en lugar de `monitor-internet.py`.

### Almacenamiento

| Recurso | Tipo | Descripción |
|---------|------|-------------|
| `internet-monitor-pv` | PersistentVolume | Volumen hostPath en `./storage/` del nodo |
| `internet-monitor-pvc` | PersistentVolumeClaim | Claim de 1Gi montado por ambos pods |

Estructura en el host:

```
storage/
├── data/
│   └── monitor.db      # Base de datos SQLite (WAL mode)
├── logs/
│   └── monitor.log     # Log del proceso de monitoreo
└── exports/
    └── internet_YYYY-MM-DD.csv   # CSV diario exportado automáticamente
    └── cortes_YYYY-MM-DD.csv     # CSV de cortes del día
```

### Configuración

| Recurso | Tipo | Descripción |
|---------|------|-------------|
| `internet-monitor-config` | ConfigMap | Variables de configuración (targets, intervalo, puertos, paths) |
| `internet-monitor-secret` | Secret | Credenciales opcionales de email para notificaciones |

Variables del ConfigMap:

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

### Servicio

| Recurso | Tipo | Puerto |
|---------|------|--------|
| `internet-monitor-dashboard` | NodePort | `30765` → `8765` |

---

## Base de datos

SQLite con tres tablas:

- **`ping_samples`** — Una fila por ping por target. Registra latencia, jitter, packet loss y si fue exitoso.
- **`outages`** — Un registro por corte detectado, con timestamp de inicio, fin y duración en segundos.
- **`daily_summaries`** — Resumen agregado por día: disponibilidad, latencia promedio/máxima, jitter, packet loss y totales de cortes.

---

## Manifests K8s

```
k8s/
├── configmap.yaml             # ConfigMap con variables de entorno
├── secret.yaml                # Secret con credenciales de email
├── persistent-volume.yaml     # PersistentVolume + PersistentVolumeClaim
├── deployment.yaml            # Deployment del monitor
├── dashboard-deployment.yaml  # Deployment del dashboard
└── dashboard-service.yaml     # Service NodePort para el dashboard
```

---

## Despliegue

### Requisitos

- Kubernetes (k3s o similar)
- Docker

### 1. Construir la imagen

```bash
docker build -t internet-monitor:latest .
```

Para k3s, importar la imagen al containerd del nodo:

```bash
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
