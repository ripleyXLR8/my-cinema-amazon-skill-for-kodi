# modules/config.py
import os
import json
import logging
import sys
import time
import requests
import secrets
import platform
from typing import Dict, Any, Optional

DATA_DIR: str = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE: str = os.path.join(DATA_DIR, "app.log")
TOKEN_FILE: str = os.path.join(DATA_DIR, "trakt_tokens.json")
APP_CONFIG_FILE: str = os.path.join(DATA_DIR, "config.json")
DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Identifiants de l'application Trakt de MyCinema, utilisés par défaut pour que
# l'utilisateur n'ait aucune application à créer : il lui suffit d'autoriser la
# sienne par code d'appareil. Vides dans les sources — ils sont injectés à la
# construction de l'image. Un utilisateur qui préfère sa propre application les
# surcharge par TRAKT_CLIENT_ID / TRAKT_CLIENT_SECRET.
# Note : le secret d'une application distribuée n'en est pas un (le flux par code
# d'appareil l'exige au moment de l'échange) ; c'est la limite connue des clients
# OAuth publics, et la raison d'être de la surcharge ci-dessus.
DEFAULT_TRAKT_CLIENT_ID: str = ""
DEFAULT_TRAKT_CLIENT_SECRET: str = ""

# Marge de renouvellement du jeton d'accès : on rafraîchit un jour avant l'échéance
# plutôt que d'attendre le premier 401 en pleine requête vocale.
TOKEN_REFRESH_MARGIN_S: int = 24 * 3600

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- Réduction du bruit des bibliothèques tierces ---
logging.getLogger("adb_shell").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("paramiko").setLevel(logging.WARNING)

logger: logging.Logger = logging.getLogger("KodiMiddleware")

TRANSLATIONS: Dict[str, Any] = {}

def load_translations() -> None:
    global TRANSLATIONS
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'translations.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            TRANSLATIONS = json.load(f)
    except Exception as e:
        logger.error(f"Erreur chargement traductions : {e}")

def get_text(key: str, lang: str = "fr", *args: Any) -> str:
    target_lang = lang if lang in TRANSLATIONS else "fr"
    text_template = TRANSLATIONS.get(target_lang, {}).get(key, "")
    if args and text_template:
        try: return text_template.format(*args)
        except: return text_template
    return text_template

def get_app_config() -> Dict[str, str]:
    config: Dict[str, str] = {
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
        "PLAYER_SELECT": os.getenv("PLAYER_SELECT", "fenlight_select.json"),
        "PROGRESS_ADDON": os.getenv("PROGRESS_ADDON", "plugin.video.pov"),
        # Voie de commande des addons Kodi. "tmdb_helper" est le defaut et le
        # reste : c'est la couche d'abstraction qui rend la skill compatible avec
        # n'importe quel lecteur. "direct" ne sert qu'aux addons dont la recette
        # est connue, et n'est jamais impose.
        "CONTROL_MODE": os.getenv("CONTROL_MODE", "tmdb_helper"),
        "DIRECT_PLAYERS": os.getenv("DIRECT_PLAYERS", ""),
        "WEB_UI_USERNAME": os.getenv("WEB_UI_USERNAME", "admin"),
        "WEB_UI_PASSWORD": os.getenv("WEB_UI_PASSWORD", "admin")
    }
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_conf = json.load(f)
                config.update(file_conf)
        except Exception as e:
            logger.error(f"Erreur lecture config.json : {e}")
    return config

def save_app_config(new_config: Dict[str, str]) -> bool:
    try:
        with open(APP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Erreur sauvegarde config.json : {e}")
        return False

def load_trakt_config() -> Dict[str, str]:
    config: Dict[str, str] = {
        "access_token": os.getenv("TRAKT_ACCESS_TOKEN", ""),
        "refresh_token": os.getenv("TRAKT_REFRESH_TOKEN", ""),
        "client_id": os.getenv("TRAKT_CLIENT_ID", DEFAULT_TRAKT_CLIENT_ID),
        "client_secret": os.getenv("TRAKT_CLIENT_SECRET", DEFAULT_TRAKT_CLIENT_SECRET)
    }
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                config.update(data)
        except Exception as e:
            logger.error(f"Erreur lecture token : {e}")
    return config

def load_trakt_token() -> Optional[str]:
    return load_trakt_config()["access_token"] or None

def save_trakt_token_data(access_token: str, refresh_token: str, client_id: Optional[str] = None, client_secret: Optional[str] = None, expires_in: Optional[Any] = None) -> bool:
    data: Dict[str, Any] = {"access_token": access_token, "refresh_token": refresh_token, "updated_at": time.time()}
    if client_id: data["client_id"] = client_id
    if client_secret: data["client_secret"] = client_secret
    if expires_in:
        try: data["expires_at"] = time.time() + float(expires_in)
        except (TypeError, ValueError): pass
    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f: json.dump(data, f)
        return True
    except Exception as e:
        logger.error(f"Erreur sauvegarde tokens : {e}")
        return False

def refresh_trakt_token_online() -> Optional[str]:
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
            save_trakt_token_data(data['access_token'], data['refresh_token'], cfg["client_id"], cfg["client_secret"], data.get('expires_in'))
            logger.info("🔑 [Trakt] Jeton d'accès renouvelé.")
            return data['access_token']
        logger.error(f"❌ [Trakt] Renouvellement du jeton refusé (HTTP {r.status_code}). Une nouvelle autorisation est nécessaire.")
    except Exception as e:
        logger.error(f"❌ [Trakt] Erreur au renouvellement du jeton : {e}")
    return None

def get_valid_trakt_token() -> Optional[str]:
    """Jeton d'accès Trakt utilisable, renouvelé d'avance s'il approche de l'expiration.

    Renvoie None si aucune autorisation n'existe. Le renouvellement anticipé évite
    qu'une demande vocale tombe sur un 401 : à ce moment-là il est trop tard pour
    rattraper quoi que ce soit dans le délai qu'Alexa accorde.
    """
    cfg = load_trakt_config()
    token = cfg.get("access_token")
    if not token: return None
    expires_at = cfg.get("expires_at")
    if expires_at:
        try:
            if float(expires_at) - time.time() < TOKEN_REFRESH_MARGIN_S:
                return refresh_trakt_token_online() or token
        except (TypeError, ValueError): pass
    return token

def get_kodi_url(conf: Dict[str, str]) -> Optional[str]:
    if conf.get("SHIELD_IP") and conf.get("KODI_PORT"):
        return f"http://{conf['SHIELD_IP']}:{conf['KODI_PORT']}/jsonrpc"
    return None

def get_secret_key() -> str:
    env_key = os.getenv("FLASK_SECRET_KEY")
    if env_key:
        return env_key
    
    config = get_app_config()
    if config.get("FLASK_SECRET_KEY"):
        return config["FLASK_SECRET_KEY"]
    
    new_key = secrets.token_hex(24)
    config["FLASK_SECRET_KEY"] = new_key
    
    if save_app_config(config):
        logger.info("🔑 Flask Secret Key générée et sauvegardée dans config.json pour persistance.")
    
    return new_key

def log_startup_banner(version: str) -> None:
    """Affiche une bannière ASCII et le récapitulatif technique au démarrage."""
    conf = get_app_config()
    trakt = load_trakt_config()
    
    def mask(s: str) -> str:
        return f"{s[:4]}****{s[-4:]}" if len(s) > 8 else "****" if s else "NON DÉFINI"

    banner = f"""
  __  __        _____ _                                
 |  \/  |_   _ / ____(_)                               
 | \  / | | | | |     _ _ __   ___ _ __ ___   __ _ 
 | |\/| | |_| | |    | | '_ \ / _ \ '_ ` _ \ / _` |
 | |  | |\__, | |____| | | | |  __/ | | | | | (_| |
 |_|  |_| \__, |\_____|_|_| |_|\___|_| |_| |_|\__,_|
          |___/                                        
    
    🚀 VERSION      : v{version}
    👨‍💻 AUTEUR       : Richard Perez
    📁 DÉPÔT GIT    : https://github.com/ripleyxlr8/my-cinema-amazon-skill-for-kodi
    🐍 PYTHON       : {platform.python_version()}
    🐳 ENVIRONNEMENT : {"Docker (Linux)" if os.path.exists('/.dockerenv') else platform.system()}
    
    [ PARAMÈTRES RÉSEAU ]
    🌐 CIBLE IP     : {conf.get('SHIELD_IP')}
    🖥️ OS CIBLE     : {conf.get('TARGET_OS').upper()}
    📶 PORT KODI    : {conf.get('KODI_PORT')}
    🔌 MAC ADDR     : {conf.get('SHIELD_MAC') or 'Non spécifiée'}
    
    [ ÉTAT DES SERVICES ]
    🎬 TMDB KEY     : {mask(conf.get('TMDB_API_KEY'))}
    🍿 TRAKT AUTH   : {'ACTIVÉ' if trakt.get('access_token') else 'MANQUANT'}
    🛡️ ALEXA SKILL  : {mask(conf.get('ALEXA_SKILL_ID'))}
    🛠️ LOG LEVEL    : {'DEBUG' if DEBUG_MODE else 'INFO'}
    
    --- Démarrage de MyCinema en cours... ---
    """
    # On utilise print pour que ça ressorte bien dans la console Docker au démarrage
    print(banner)
    logger.info(f"Système MyCinema initialisé avec succès (v{version}).")
