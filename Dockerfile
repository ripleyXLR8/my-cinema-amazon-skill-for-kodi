FROM python:3.9-slim

WORKDIR /app

# Ajout de "curl" dans la liste des paquets
RUN apt-get update && apt-get install -y \
    android-tools-adb \
    iputils-ping \
    tini \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Déclaration du Healthcheck pour Unraid/Docker
# Docker va tester l'URL toutes les 30s.
# S'il n'y a pas de réponse 200 au bout de 3 essais, il passe en "Unhealthy".
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:5000/health || exit 1

# Utilisation de Tini comme gestionnaire de processus principal (PID 1)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Lancement de l'application via Gunicorn (1 worker, 4 threads pour supporter la concurrence sans dupliquer le patcher)
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5000", "app:app"]
