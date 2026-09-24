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

# Identifiants de l'application Trakt de MyCinema, injectés à la construction pour
# que l'utilisateur n'ait aucune application à créer : il lui suffit d'autoriser
# la sienne depuis la page de réglages.
# Le secret d'un client OAuth public n'en est pas vraiment un — il est extractible
# de l'image, comme chez tous les addons Kodi équivalents. Qui préfère sa propre
# application surcharge simplement ces deux variables à l'exécution.
ARG TRAKT_CLIENT_ID=""
ARG TRAKT_CLIENT_SECRET=""
ENV TRAKT_CLIENT_ID=$TRAKT_CLIENT_ID \
    TRAKT_CLIENT_SECRET=$TRAKT_CLIENT_SECRET

COPY . .

# Déclaration du Healthcheck pour Unraid/Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:5000/health || exit 1

# Utilisation de Tini comme gestionnaire de processus principal (PID 1)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Lancement de l'application via Gunicorn
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5000", "app:app"]
