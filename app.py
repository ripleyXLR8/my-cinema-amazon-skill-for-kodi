# ==============================================================================
# FICHIER : app.py
# VERSION : 1.6.1
# DATE    : 2025-12-05 17:00:00 (CET)
# AUTEUR  : Richard Perez (richard@perez-mail.fr)
#
# DESCRIPTION : 
# Skill Alexa pour contrôle vocal de Kodi sur Nvidia Shield.
# UPDATE v1.6.1 : Restauration de la bannière de démarrage détaillée 
# avec status des tokens Trakt gérés dynamiquement.
# ==============================================================================

from flask import Flask, request, jsonify
import requests
import threading
import time
import subprocess
import os
import sys
import logging
import json
from wakeonlan import send_magic_packet

# --- CONFIGURATION LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("KodiMiddleware")

# --- METADATA ---
APP_VERSION = "1.6.1"
APP_DATE = "2025-12-05"
APP_AUTHOR = "Richard Perez"

app = Flask(__name__)

# ==========================================
# 1. CONFIGURATION & VARIABLES
# ==========================================

# Mode Debug
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
if DEBUG_MODE:
    logger.setLevel(logging.DEBUG)
    logger.debug("MODE DEBUG ACTIVÉ : Logs verbeux.")

# --- FICHIER DE PERSISTANCE DES TOKENS ---
DATA_DIR = "/app/data"
TOKEN_FILE = os.path.join(DATA_DIR, "trakt_tokens.json")

# --- API KEYS (ENV) ---
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TRAKT_CLIENT_ID = os.getenv("TRAKT_CLIENT_ID")
TRAKT_CLIENT_SECRET = os.getenv("TRAKT_CLIENT_SECRET")
# Les tokens initiaux (pour le premier lancement seulement)
ENV_TRAKT_ACCESS_TOKEN = os.getenv("TRAKT_ACCESS_TOKEN")
ENV_TRAKT_REFRESH_TOKEN = os.getenv("TRAKT_REFRESH_TOKEN")

# Réseau & Kodi
SHIELD_IP = os.getenv("SHIELD_IP")
SHIELD_MAC = os.getenv("SHIELD_MAC")
KODI_PORT = os.getenv("KODI_PORT")
KODI_USER = os.getenv("KODI_USER")
KODI_PASS = os.getenv("KODI_PASS")

# Players
PLAYER_DEFAULT = os.getenv("PLAYER_DEFAULT", "fenlight_auto.json")
PLAYER_SELECT = os.getenv("PLAYER_SELECT", "fenlight_select.json")

# Auto-Patcher
FENLIGHT_UTILS_REMOTE_PATH = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py"
FENLIGHT_LOCAL_TEMP = "/tmp/kodi_utils.py"
PATCH_CHECK_INTERVAL = 3600 

if SHIELD_IP and KODI_PORT:
    KODI_BASE_URL = f"http://{SHIELD_IP}:{KODI_PORT}/jsonrpc"
else:
    KODI_BASE_URL = None
    logger.critical("Configuration incomplète : SHIELD_IP ou KODI_PORT manquant.")

# ==========================================
# 2. GESTION DES TOKENS
# ==========================================

def load_trakt_token():
    """Charge le token depuis le fichier JSON ou initialise avec les ENV vars."""
    # 1. Essayer de charger depuis le fichier JSON (Prioritaire)
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                if data.get('access_token') and data.get('refresh_token'):
                    return data['access_token']
        except Exception as e:
            logger.error(f"[TOKEN] Erreur lecture fichier token : {e}")

    # 2. Si pas de fichier, utiliser les variables d'environnement (Bootstrap)
    if ENV_TRAKT_ACCESS_TOKEN and ENV_TRAKT_REFRESH_TOKEN:
        logger.info("[TOKEN] Initialisation du fichier tokens depuis les variables d'environnement.")
        save_trakt_token_data(ENV_TRAKT_ACCESS_TOKEN, ENV_TRAKT_REFRESH_TOKEN)
        return ENV_TRAKT_ACCESS_TOKEN
    
    logger.error("[TOKEN] Aucun token disponible (ni fichier, ni ENV).")
    return None

def get_refresh_token_from_storage():
    """Récupère le refresh token stocké pour le renouvellement."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f).get('refresh_token')
        except: pass
    return ENV_TRAKT_REFRESH_TOKEN

def save_trakt_token_data(access_token, refresh_token):
    """Sauvegarde les nouveaux tokens dans le volume persistant."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "updated_at": time.time()
    }
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(data, f)
        logger.info("[TOKEN] Tokens mis à jour et sauvegardés dans trakt_tokens.json ✅")
    except Exception as e:
        logger.error(f"[TOKEN] Impossible de sauvegarder les tokens : {e}")

def refresh_trakt_token_online():
    """Effectue la requête de renouvellement auprès de Trakt."""
    logger.info("[TOKEN] Tentative de renouvellement du token...")
    
    refresh_token = get_refresh_token_from_storage()
    if not refresh_token or not TRAKT_CLIENT_SECRET:
        logger.error("[TOKEN] Impossible de renouveler : Refresh Token ou Client Secret manquant.")
        return None

    url = "https://api.trakt.tv/oauth/token"
    payload = {
        "refresh_token": refresh_token,
        "client_id": TRAKT_CLIENT_ID,
        "client_secret": TRAKT_CLIENT_SECRET,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "grant_type": "refresh_token"
    }
    
    try:
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            new_access = data['access_token']
            new_refresh = data['refresh_token']
            save_trakt_token_data(new_access, new_refresh)
            return new_access
        else:
            logger.error(f"[TOKEN] Echec renouvellement (Code {r.status_code}): {r.text}")
    except Exception as e:
        logger.error(f"[TOKEN] Exception lors du renouvellement : {e}")
    
    return None

# ==========================================
# 3. TRADUCTIONS & PATCHER
# ==========================================
TRANSLATIONS = {}

def load_translations():
    global TRANSLATIONS
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'translations.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            TRANSLATIONS = json.load(f)
        logger.info(f"Traductions chargées : {list(TRANSLATIONS.keys())}")
    except Exception as e:
        logger.error(f"ERREUR CRITIQUE : Impossible de charger translations.json : {e}")
        TRANSLATIONS = {"fr": {"not_understood": "Erreur de traduction"}, "en": {"not_understood": "Translation Error"}}

def get_text(key, lang="fr", *args):
    target_lang = lang if lang in TRANSLATIONS else "fr"
    text_template = TRANSLATIONS.get(target_lang, {}).get(key, "")
    if not text_template and target_lang != "fr":
        text_template = TRANSLATIONS.get("fr", {}).get(key, "")
    if args and text_template:
        try: return text_template.format(*args)
        except: return text_template
    return text_template

def check_and_patch_fenlight():
    if not SHIELD_IP: return
    if DEBUG_MODE: logger.info(f"[PATCHER] Vérification intégrité Fen Light (kodi_utils.py)...")
    try:
        subprocess.run(["adb", "disconnect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "connect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except: return

    if os.path.exists(FENLIGHT_LOCAL_TEMP): os.remove(FENLIGHT_LOCAL_TEMP)
    try:
        res = subprocess.run(["adb", "pull", FENLIGHT_UTILS_REMOTE_PATH, FENLIGHT_LOCAL_TEMP], capture_output=True, timeout=10)
        if res.returncode != 0: return 
    except: return

    try:
        with open(FENLIGHT_LOCAL_TEMP, 'r', encoding='utf-8') as f: content = f.read()
        patched = False
        
        if "if mode == 'playback.%s' % playback_key():" in content:
            content = content.replace("if mode == 'playback.%s' % playback_key():", "if True: # mode == 'playback.%s' % playback_key():")
            patched = True
        if "if not playback_key() in params:" in content:
            content = content.replace("if not playback_key() in params:", "if False: # not playback_key() in params:")
            patched = True
        
        if patched:
            with open(FENLIGHT_LOCAL_TEMP, 'w', encoding='utf-8') as f: f.write(content)
            subprocess.run(["adb", "push", FENLIGHT_LOCAL_TEMP, FENLIGHT_UTILS_REMOTE_PATH], capture_output=True)
            logger.info("[PATCHER] Patch appliqué.")
    except Exception as e: logger.error(f"[PATCHER] Erreur: {e}")

def patcher_scheduler():
    while True:
        check_and_patch_fenlight()
        time.sleep(PATCH_CHECK_INTERVAL)

# ==========================================
# 4. GESTION PUISSANCE
# ==========================================
def is_kodi_responsive():
    if not KODI_BASE_URL: return False
    try:
        r = requests.get(KODI_BASE_URL, timeout=2)
        if r.status_code in [200, 401, 405]: return True
    except: pass
    return False

def wake_and_start_kodi():
    if not SHIELD_IP or not SHIELD_MAC: return False
    if is_kodi_responsive(): return True
    logger.info(f"[POWER] Réveil de la Shield ({SHIELD_IP})...")
    try: send_magic_packet(SHIELD_MAC)
    except: pass
    try:
        subprocess.run(["adb", "connect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(0.5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
    except: pass
    if is_kodi_responsive(): return True
    try: subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
    except: pass
    for i in range(45):
        if is_kodi_responsive(): 
            time.sleep(4)
            return True
        time.sleep(1)
    return False

# ==========================================
# 5. API CHECKER
# ==========================================
def verify_api_status():
    logger.info("--- VÉRIFICATION DES ACCÈS API ---")
    
    # TMDB
    if not TMDB_API_KEY: logger.error("[API] TMDB_API_KEY manquant !")
    else:
        try:
            r = requests.get(f"https://api.themoviedb.org/3/movie/19995?api_key={TMDB_API_KEY}", timeout=5)
            if r.status_code == 200: logger.info("[API] TMDB : OK ✅")
            else: logger.warning(f"[API] TMDB : Erreur ({r.status_code})")
        except: logger.error("[API] TMDB : Injoignable")

    # TRAKT
    token = load_trakt_token()
    if not token or not TRAKT_CLIENT_ID:
        logger.error("[API] TRAKT : Token manquant !")
    else:
        headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': TRAKT_CLIENT_ID, 'Authorization': f'Bearer {token}'}
        try:
            r = requests.get("https://api.trakt.tv/users/settings", headers=headers, timeout=5)
            if r.status_code == 200:
                logger.info("[API] TRAKT : Token OK ✅")
            elif r.status_code == 401:
                logger.warning("[API] TRAKT : Token expiré (401). Tentative de renouvellement immédiat...")
                new_token = refresh_trakt_token_online()
                if new_token: logger.info("[API] TRAKT : Token renouvelé avec succès ! ✅")
                else: logger.critical("[API] TRAKT : Echec du renouvellement ❌")
            else:
                logger.warning(f"[API] TRAKT : Statut {r.status_code}")
        except: logger.error("[API] TRAKT : Injoignable")
    logger.info("-" * 30)

# ==========================================
# 6. HELPERS
# ==========================================

def get_trakt_next_episode(tmdb_show_id):
    current_token = load_trakt_token()
    if not TRAKT_CLIENT_ID or not current_token:
        logger.warning("[TRAKT] Token manquant.")
        return None, None
    
    headers = {
        'Content-Type': 'application/json', 
        'trakt-api-version': '2', 
        'trakt-api-key': TRAKT_CLIENT_ID, 
        'Authorization': f'Bearer {current_token}'
    }
    
    def make_request(url):
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 401:
            logger.warning("[TRAKT] 401 Unauthorized détecté pendant l'appel. Renouvellement...")
            new_t = refresh_trakt_token_online()
            if new_t:
                headers['Authorization'] = f'Bearer {new_t}'
                return requests.get(url, headers=headers, timeout=2)
        return r

    try:
        search_url = f"https://api.trakt.tv/search/tmdb/{tmdb_show_id}?type=show"
        r = make_request(search_url)
        if r.status_code != 200: return None, None
        results = r.json()
        if not results: return None, None
        trakt_id = results[0]['show']['ids']['trakt']
        
        progress_url = f"https://api.trakt.tv/shows/{trakt_id}/progress/watched"
        r = make_request(progress_url)
        if r.status_code != 200: return None, None
        data = r.json()
        next_ep = data.get('next_episode')
        if next_ep: return next_ep['season'], next_ep['number']
    except Exception as e:
        logger.error(f"[TRAKT] Exception : {e}")
    return None, None

def search_tmdb_movie(query, year=None, lang="fr"):
    if not TMDB_API_KEY: return None, None, None
    tmdb_lang = "fr-FR" if lang == "fr" else "en-US"
    base_url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": tmdb_lang}
    if year: params['year'] = year
    try:
        r = requests.get(base_url, params=params, timeout=2)
        data = r.json()
        if data.get('results'):
            res = data['results'][0]
            return res['id'], res['title'], res.get('release_date', '')[:4]
    except: pass
    return None, None, None

def search_tmdb_show(query, lang="fr"):
    if not TMDB_API_KEY: return None, None
    tmdb_lang = "fr-FR" if lang == "fr" else "en-US"
    base_url = "https://api.themoviedb.org/3/search/tv"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": tmdb_lang}
    try:
        r = requests.get(base_url, params=params, timeout=2)
        data = r.json()
        if data.get('results'):
            res = data['results'][0]
            return res['id'], res['name']
    except: pass
    return None, None

def check_episode_exists(tmdb_id, season, episode):
    if not TMDB_API_KEY: return False
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}"
    try:
        r = requests.get(url, params={"api_key": TMDB_API_KEY}, timeout=2)
        return r.status_code == 200
    except: return True

def get_tmdb_last_aired(tmdb_id):
    if not TMDB_API_KEY: return None, None
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
    try:
        r = requests.get(url, params={"api_key": TMDB_API_KEY}, timeout=2)
        data = r.json()
        last_ep = data.get('last_episode_to_air')
        if last_ep: return last_ep['season_number'], last_ep['episode_number']
    except: pass
    return None, None

def get_playback_url(tmdb_id, media_type, season=None, episode=None, force_select=False):
    p_def = PLAYER_DEFAULT if PLAYER_DEFAULT else "fenlight_auto.json"
    p_sel = PLAYER_SELECT if PLAYER_SELECT else "fenlight_select.json"
    target_player = p_sel if force_select else p_def
    base = "plugin://plugin.video.themoviedb.helper/?info=play"
    url = f"{base}&player={target_player}"
    if media_type == "movie": return f"{url}&tmdb_id={tmdb_id}&type=movie"
    elif media_type == "episode": return f"{url}&tmdb_id={tmdb_id}&season={season}&episode={episode}&type=episode"
    return None

def worker_process(plugin_url):
    logger.info(">>> DÉBUT PROCESSUS LECTURE")
    if not wake_and_start_kodi(): 
        logger.error(">>> ABANDON : Kodi injoignable.")
        return
    
    logger.info(f"[KODI] Envoi URL : {plugin_url}")
    payload = {"jsonrpc": "2.0", "method": "Player.Open", "params": {"item": {"file": plugin_url}}, "id": 1}
    try:
        auth = (KODI_USER, KODI_PASS) if KODI_USER and KODI_PASS else None
        r = requests.post(KODI_BASE_URL, json=payload, auth=auth, timeout=5)
        if r.status_code == 200:
            logger.info(f"[KODI] Réponse RPC : {r.json().get('result', 'OK')}")
        else:
            logger.error(f"[KODI] Erreur HTTP : {r.status_code}")
    except Exception as e:
        logger.error(f"[KODI] Exception : {e}")
    logger.info(">>> FIN PROCESSUS LECTURE")

# ==========================================
# 7. ROUTE FLASK
# ==========================================

@app.route('/alexa-webhook', methods=['POST'])
def alexa_handler():
    req_data = request.get_json()
    if not req_data or 'request' not in req_data: return jsonify({"error": "Invalid Request"}), 400

    req_type = req_data['request']['type']
    session = req_data.get('session', {})
    attributes = session.get('attributes', {})
    full_locale = req_data['request'].get('locale', 'fr-FR')
    lang = full_locale.split('-')[0]
    
    logger.info(f"Requête reçue ({req_type}) - Langue détectée : {lang.upper()} ({full_locale})")
    if DEBUG_MODE: logger.debug(json.dumps(req_data))

    if req_type == "LaunchRequest":
        return jsonify(build_response(get_text("launch", lang), end_session=False))

    if req_type == "IntentRequest":
        intent = req_data['request']['intent']
        intent_name = intent['name']
        slots = intent.get('slots', {})
        slot_source_mode = slots.get('SourceMode', {}).get('value')
        force_select = True if slot_source_mode else attributes.get('force_select', False)
        manual_msg = get_text("manual_select", lang) if force_select else ""

        if intent_name == "ResumeTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            if not query: return jsonify(build_response(get_text("ask_show", lang), end_session=False))
            tmdb_id, title = search_tmdb_show(query, lang=lang)
            if not tmdb_id: return jsonify(build_response(get_text("show_not_found", lang, query)))
            s, e = get_trakt_next_episode(tmdb_id)
            if s and e:
                url = get_playback_url(tmdb_id, "episode", s, e, force_select)
                threading.Thread(target=worker_process, args=(url,)).start()
                return jsonify(build_response(get_text("resume_show", lang, title, s, e, manual_msg)))
            else:
                return jsonify(build_response(get_text("no_progress", lang, title), end_session=False))

        elif intent_name == "PlayMovieIntent":
            query = slots.get('MovieName', {}).get('value')
            year_query = slots.get('MovieYear', {}).get('value')
            if not query: return jsonify(build_response(get_text("ask_movie", lang), end_session=False))
            movie_id, movie_title, movie_year = search_tmdb_movie(query, year=year_query, lang=lang)
            if movie_id:
                url = get_playback_url(movie_id, "movie", force_select=force_select)
                threading.Thread(target=worker_process, args=(url,)).start()
                year_str = f" ({movie_year})" if lang == 'en' else f" de {movie_year}"
                if not movie_year: year_str = ""
                return jsonify(build_response(get_text("launch_movie", lang, movie_title, year_str, manual_msg)))
            else:
                return jsonify(build_response(get_text("movie_not_found", lang, query)))

        elif intent_name == "PlayTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            season = slots.get('Season', {}).get('value')
            episode = slots.get('Episode', {}).get('value')
            if not query and attributes.get('pending_show_id'):
                tmdb_id, title = attributes['pending_show_id'], attributes['pending_show_name']
            elif query:
                tmdb_id, title = search_tmdb_show(query, lang=lang)
            else:
                return jsonify(build_response(get_text("ask_which_show", lang), end_session=False))
            if not tmdb_id: return jsonify(build_response(get_text("show_not_found", lang, query)))
            if season and episode:
                if check_episode_exists(tmdb_id, season, episode):
                    url = get_playback_url(tmdb_id, "episode", season, episode, force_select)
                    threading.Thread(target=worker_process, args=(url,)).start()
                    return jsonify(build_response(get_text("launch_show", lang, title, season, episode, manual_msg)))
                else:
                    return jsonify(build_response(get_text("episode_not_found", lang), end_session=False))
            else:
                trakt_s, trakt_e = get_trakt_next_episode(tmdb_id)
                tmdb_last_s, tmdb_last_e = get_tmdb_last_aired(tmdb_id)
                new_attr = {
                    "pending_show_id": tmdb_id, "pending_show_name": title,
                    "step": "ask_playback_method", "force_select": force_select,
                    "trakt_next_s": trakt_s, "trakt_next_e": trakt_e,
                    "tmdb_last_s": tmdb_last_s, "tmdb_last_e": tmdb_last_e
                }
                msg = get_text("ask_resume", lang, title, trakt_s, trakt_e) if trakt_s else get_text("ask_start", lang, title)
                return jsonify(build_response(msg, end_session=False, attributes=new_attr))

        elif intent_name in ["AMAZON.YesIntent", "ResumeIntent", "ReprendreIntent"]: 
            if attributes.get('step') == 'ask_playback_method':
                if attributes.get('trakt_next_s'):
                    s, e = attributes['trakt_next_s'], attributes['trakt_next_e']
                    title = attributes['pending_show_name']
                    url = get_playback_url(attributes['pending_show_id'], "episode", s, e, force_select)
                    threading.Thread(target=worker_process, args=(url,)).start()
                    manual_txt = get_text("manual_select", lang) if force_select else ""
                    return jsonify(build_response(get_text("resume_show", lang, title, s, e, manual_txt)))
                else:
                    return jsonify(build_response(get_text("no_history", lang), end_session=False))
            else:
                return jsonify(build_response(get_text("nothing_pending", lang)))

        elif intent_name == "LatestEpisodeIntent":
            if attributes.get('step') == 'ask_playback_method':
                s, e = attributes['tmdb_last_s'], attributes['tmdb_last_e']
                title = attributes.get('pending_show_name', 'show')
                url = get_playback_url(attributes['pending_show_id'], "episode", s, e, force_select)
                threading.Thread(target=worker_process, args=(url,)).start()
                return jsonify(build_response(get_text("launch_last", lang, title)))
            return jsonify(build_response(get_text("unavailable", lang)))

        elif intent_name in ["AMAZON.NoIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"]:
            return jsonify(build_response(get_text("cancelled", lang)))

    return jsonify(build_response(get_text("not_understood", lang)))

def build_response(text, end_session=True, attributes={}):
    return {"version": "1.0", "sessionAttributes": attributes, "response": {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end_session}}

# --- STARTUP ---
def print_startup_banner():
    masked_key = f"{TMDB_API_KEY[:4]}...{TMDB_API_KEY[-4:]}" if TMDB_API_KEY else "MISSING"
    
    # Check si le token est chargé (soit via ENV, soit via fichier JSON)
    current_token = load_trakt_token()
    if current_token:
        masked_trakt = "Loaded (from file/env)"
    else:
        masked_trakt = "MISSING"

    print("\n" + "="*50)
    print(f" KODI ALEXA CONTROLLER")
    print(f" Version : {APP_VERSION} (Auto-Refresh Trakt Enabled)")
    print(f" Date    : {APP_DATE}")
    print(f" Author  : {APP_AUTHOR}")
    print(f" Debug   : {'ON' if DEBUG_MODE else 'OFF'}")
    print("="*50)
    print(f" [NET] Shield IP      : {SHIELD_IP if SHIELD_IP else 'MISSING'}")
    print(f" [NET] Kodi Endpoint  : {KODI_BASE_URL if KODI_BASE_URL else 'INVALID'}")
    print(f" [CFG] Player Auto    : {PLAYER_DEFAULT if PLAYER_DEFAULT else 'MISSING'}")
    print(f" [CFG] Player Select  : {PLAYER_SELECT if PLAYER_SELECT else 'MISSING'}")
    print(f" [API] TMDB Key       : {masked_key}")
    print(f" [API] Trakt Token    : {masked_trakt}")
    print(f" [SYS] Auto-Patcher   : ACTIVE (Interval: {PATCH_CHECK_INTERVAL}s)")
    print("="*50 + "\n")
    sys.stdout.flush()

if __name__ == '__main__':
    print_startup_banner()
    verify_api_status()
    load_translations() 
    patcher_thread = threading.Thread(target=patcher_scheduler, daemon=True)
    patcher_thread.start()
    app.run(host='0.0.0.0', port=5000)
