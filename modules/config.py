# modules/config.py
import os
import json
import logging
import sys
import time
import requests

DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = os.path.join(DATA_DIR, "app.log")
TOKEN_FILE = os.path.join(DATA_DIR, "trakt_tokens.json")
APP_CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("KodiMiddleware")

TRANSLATIONS = {}

def load_translations():
    global TRANSLATIONS
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'translations.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            TRANSLATIONS = json.load(f)
    except Exception as e:
        logger.error(f"Erreur chargement traductions : {e}")

def get_text(key, lang="fr", *args):
    target_lang = lang if lang in TRANSLATIONS else "fr"
    text_template = TRANSLATIONS.get(target_lang, {}).get(key, "")
    if args and text_template:
        try: return text_template.format(*args)
        except: return text_template
    return text_template

def get_app_config():
    config = {
        "TMDB_API_KEY": os.getenv("TMDB_API_KEY", ""),
        "ALEXA_SKILL_ID": os.getenv("ALEXA_SKILL_ID", ""),
        "TARGET_OS": os.getenv("TARGET_OS", "android").lower(),
        "SSH_USER": os.getenv("SSH_USER", "root"),
        "SSH_PASS": os.getenv("SSH_PASS", "libreelec"),
        "SHIELD_IP": os.getenv("SHIELD_IP", ""),
        "SHIELD_MAC": os.getenv("SHIELD_MAC", ""),
        "KODI_PORT": os.getenv("KODI_PORT", "8080"),
        "KODI_USER": os.getenv("KODI_USER", "kodi"),
        "KODI_PASS": os.getenv("KODI_PASS", "kodi"),
        "PLAYER_DEFAULT": os.getenv("PLAYER_DEFAULT", "fenlight_auto.json"),
        "PLAYER_SELECT": os.getenv("PLAYER_SELECT", "fenlight_select.json")
    }
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_conf = json.load(f)
                config.update(file_conf)
        except Exception as e:
            logger.error(f"Erreur lecture config.json : {e}")
    return config

def save_app_config(new_config):
    try:
        with open(APP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Erreur sauvegarde config.json : {e}")
        return False

def load_trakt_config():
    config = {
        "access_token": os.getenv("TRAKT_ACCESS_TOKEN", ""),
        "refresh_token": os.getenv("TRAKT_REFRESH_TOKEN", ""),
        "client_id": os.getenv("TRAKT_CLIENT_ID", ""),
        "client_secret": os.getenv("TRAKT_CLIENT_SECRET", "")
    }
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                config.update(data)
        except Exception as e:
            logger.error(f"Erreur lecture token : {e}")
    return config

def load_trakt_token():
    return load_trakt_config()["access_token"] or None

def save_trakt_token_data(access_token, refresh_token, client_id=None, client_secret=None):
    data = {"access_token": access_token, "refresh_token": refresh_token, "updated_at": time.time()}
    if client_id: data["client_id"] = client_id
    if client_secret: data["client_secret"] = client_secret
    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f: json.dump(data, f)
        return True
    except Exception as e:
        logger.error(f"Erreur sauvegarde tokens : {e}")
        return False

def refresh_trakt_token_online():
    cfg = load_trakt_config()
    if not all([cfg["refresh_token"], cfg["client_secret"], cfg["client_id"]]): return None
    try:
        r = requests.post("https://api.trakt.tv/oauth/token", json={
            "refresh_token": cfg["refresh_token"], "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"], "grant_type": "refresh_token",
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob"
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            save_trakt_token_data(data['access_token'], data['refresh_token'], cfg["client_id"], cfg["client_secret"])
            return data['access_token']
    except Exception: pass
    return None

def get_kodi_url(conf):
    if conf.get("SHIELD_IP") and conf.get("KODI_PORT"):
        return f"http://{conf['SHIELD_IP']}:{conf['KODI_PORT']}/jsonrpc"
    return None
