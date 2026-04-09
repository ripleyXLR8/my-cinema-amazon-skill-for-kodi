FROM python:3.9-slim

WORKDIR /app

# Installation des outils système (ADB + Ping + Tini)
RUN apt-get update && apt-get install -y \
    android-tools-adb \
    iputils-ping \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Utilisation de Tini comme gestionnaire de processus principal (PID 1)
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "app.py"]
