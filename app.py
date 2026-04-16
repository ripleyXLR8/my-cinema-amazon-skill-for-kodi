# app.py
# VERSION : 2.6.1
# DATE    : 2026-04-14
# DESCRIPTION : Refactoring - Fix Initialisation Gunicorn (Translations & Patcher) + Type Hinting + Blueprints

from flask import Flask
import threading
import os

# Imports locaux (Initialisation globale)
from modules.config import load_translations, get_secret_key
from modules.patcher import patcher_scheduler

# Imports des Blueprints
from routes.web import web_bp
from routes.api import api_bp

APP_VERSION: str = "2.6.2"

app = Flask(__name__)
# Génère une clé sécurisée ou utilise la clé persistante générée au premier démarrage
app.secret_key = get_secret_key()

# Enregistrement des Blueprints
app.register_blueprint(web_bp)
app.register_blueprint(api_bp)

# ==========================================
# INITIALISATION GLOBALE (Gunicorn & Local)
# ==========================================

# Ces fonctions s'exécutent dès que Gunicorn importe le fichier app.py
load_translations()

# Sécurité : on s'assure de ne pas lancer plusieurs threads si l'app est rechargée
if not any(thread.name == "PatcherThread" for thread in threading.enumerate()):
    patcher_thread = threading.Thread(target=patcher_scheduler, daemon=True, name="PatcherThread")
    patcher_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
