FROM python:3.9-slim

WORKDIR /app

# Ajout de "curl" (Healthcheck) et "iputils-ping" (Online check), ADB système retiré !
RUN apt-get update && apt-get install -y \
    iputils-ping \
    tini \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Déclaration du Healthcheck pour Unraid/Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:5000/health || exit 1

# Utilisation de Tini comme gestionnaire de processus principal (PID 1)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Lancement de l'application via Gunicorn
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5000", "app:app"]
