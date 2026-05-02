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

## Prerrequisitos

Para usar Docker Compose necesitás tener Docker instalado. Seguí las instrucciones según tu sistema operativo:

### Windows

1. Descargá **Docker Desktop** desde [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Ejecutá el instalador y seguí los pasos (acepta los valores por defecto)
3. Reiniciá la PC cuando lo pida
4. Abrí Docker Desktop y esperá a que el ícono de la ballena en la barra de tareas quede estable (deja de animarse)
5. Abrí una terminal (buscá "PowerShell" o "CMD" en el menú inicio) y verificá que funciona:
   ```
   docker --version
   ```

### Linux (Ubuntu / Debian)

Abrí una terminal y ejecutá estos comandos uno por uno:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

Cerrá sesión y volvé a entrar para que el último comando tenga efecto. Luego verificá:

```bash
docker --version
```

> En otras distribuciones (Fedora, Arch, etc.) consultá la [documentación oficial de Docker](https://docs.docker.com/engine/install/).

---

## Inicio rápido con Docker Compose

> Esta es la opción recomendada si solo querés monitorear tu conexión en una PC o servidor con Docker instalado, sin necesidad de Kubernetes.

### Paso 1 — Descargá el proyecto

```bash
git clone https://github.com/LeoOslos/internet-monitor-k8s.git
cd internet-monitor-k8s
```

### Paso 2 — Configurá las credenciales (opcional)

Si querés recibir notificaciones por email cuando se corte la conexión, copiá el archivo de ejemplo y completá tus datos:

```bash
cp .env.example .env
```

Abrí `.env` con cualquier editor de texto y completá los campos. Si no querés notificaciones, no hace falta hacer nada — el monitor funciona sin email.

### Paso 3 — Levantá los servicios

```bash
docker compose up -d
```

Este comando construye la imagen y arranca el monitor y el dashboard en segundo plano. La primera vez tarda unos minutos mientras descarga las dependencias.

### Paso 4 — Abrí el dashboard

Abrí tu navegador y entrá a:

```
http://localhost:9090
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
docker compose logs -f dashboard
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
| `dashboard` | `internet-monitor:latest` | Servidor HTTP que lee la DB y expone el dashboard en el puerto 9090 |

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
| `DASHBOARD_PORT` | `8765` | Puerto interno del servidor HTTP |
| `DB_PATH` | `/app/data/monitor.db` | Path de la base de datos SQLite |
| `LOG_DIR` | `/app/logs` | Directorio de logs |
| `CSV_EXPORT_DIR` | `/app/exports` | Directorio de exportaciones CSV |
| `EMAIL_ENABLED` | `false` | Activa notificaciones por email al recuperarse la conexión |
| `EMAIL_FROM` | — | Cuenta Gmail de origen (definida en `.env`) |
| `EMAIL_TO` | — | Destinatario de las notificaciones (definida en `.env`) |
| `EMAIL_APP_PASSWORD` | — | App Password de Gmail (definida en `.env`) |

Las credenciales de email se leen desde el archivo `.env` en la raíz del proyecto. Ese archivo no se sube al repositorio (está en `.gitignore`). Usá `.env.example` como plantilla.

---

## Base de datos

SQLite con tres tablas:

- **`ping_samples`** — Una fila por ping por target. Registra latencia, jitter, packet loss y si fue exitoso.
- **`outages`** — Un registro por corte detectado, con timestamp de inicio, fin y duración en segundos.
- **`daily_summaries`** — Resumen agregado por día: disponibilidad, latencia promedio/máxima, jitter, packet loss y totales de cortes.

---

## Solución de problemas

### `docker compose logs dashboard` no muestra nada

Python buferea stdout cuando no corre en una terminal. El `docker-compose.yml` ya incluye `PYTHONUNBUFFERED=1` y el flag `-u` en el comando para forzar flush inmediato. Si aun así no ves logs, reiniciá el contenedor:

```bash
docker compose restart dashboard
docker compose logs dashboard
```

Deberías ver `Dashboard corriendo en http://0.0.0.0:8765` al arrancar.

### El dashboard devuelve error 503

El dashboard arranca antes de que el monitor cree la base de datos. Esperá unos segundos y recargá la página — en cuanto el monitor complete su primer ciclo (máximo 30 segundos) el dashboard funciona normalmente.

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

## Despliegue en Kubernetes (avanzado)

> Usá esta opción si tenés un cluster Kubernetes y querés aprovechar su orquestación, reinicio automático de pods y gestión de volúmenes persistentes.

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
