# Imagen base con Python
FROM python:3.12-slim

# Instalar ping y otras herramientas de red que usa el monitor
RUN apt-get update && \
    apt-get install -y iputils-ping && \
    rm -rf /var/lib/apt/lists/*

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar e instalar dependencias primero
# (esto aprovecha el cache de Docker, si el código cambia pero las deps no, no reinstala)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY src/ .

# El contenedor no guarda datos acá, los volúmenes se montan desde afuera
# Crear directorios que el proceso espera encontrar
RUN mkdir -p /app/data /app/logs /app/exports

CMD ["python", "monitor-internet.py"]
