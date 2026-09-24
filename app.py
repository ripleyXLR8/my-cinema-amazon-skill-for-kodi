# app.py
# DATE    : 2026-04-14
# DESCRIPTION : Point d'entrée Flask/Gunicorn (traductions, blueprints)

from flask import Flask

# Imports locaux (Initialisation globale)
from modules.config import load_translations, get_secret_key, log_startup_banner

# Imports des Blueprints
from routes.web import web_bp
from routes.api import api_bp

APP_VERSION: str = "2.8.1"

app = Flask(__name__)
# Génère une clé sécurisée ou utilise la clé persistante générée au premier démarrage
app.secret_key = get_secret_key()

# Injection de la version pour les Blueprints
app.config['APP_VERSION'] = APP_VERSION

# Enregistrement des Blueprints
app.register_blueprint(web_bp)
app.register_blueprint(api_bp)

# ==========================================
# INITIALISATION GLOBALE (Gunicorn & Local)
# ==========================================

# Ces fonctions s'exécutent dès que Gunicorn importe le fichier app.py
load_translations()
log_startup_banner(APP_VERSION)

# Garde la copie locale du cache de progression a jour hors de toute demande
# vocale : le chemin vocal ne doit jamais attendre ADB, et doit pouvoir repondre
# alors meme que l'appareil est eteint -- c'est justement le moment ou l'on
# demande a Alexa de reprendre une serie.
from modules.progress import demarrer_rafraichissement
demarrer_rafraichissement()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
