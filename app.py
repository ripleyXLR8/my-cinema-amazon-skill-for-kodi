# ==============================================================================
# FICHIER : app.py
# VERSION : 1.4.6
# DATE    : 2025-11-29 14:40:00 (CET)
# AUTEUR  : Richard Perez (richard@perez-mail.fr)
#
# DESCRIPTION : 
# Skill Alexa pour contrôle vocal de Kodi sur Nvidia Shield.
# UPDATE v1.4.6 : Augmentation des timeouts ADB (5s) pour éviter les échecs
# de réveil sur les systèmes lents ou chargés.
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
APP_VERSION = "1.4.5"
APP_DATE = "2025-11-27"
APP_AUTHOR = "Richard Perez"

app = Flask(__name__)

# ==========================================
# 1. CONFIGURATION & TRADUCTIONS
# ==========================================

# Mode Debug
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
if DEBUG_MODE:
    logger.setLevel(logging.DEBUG)
    logger.debug("MODE DEBUG ACTIVÉ : Logs verbeux.")

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
        try:
            return text_template.format(*args)
        except IndexError:
            logger.warning(f"Erreur de formatage pour la clé '{key}'")
            return text_template
    return text_template

# Réseau Shield
SHIELD_IP = os.getenv("SHIELD_IP")
SHIELD_MAC = os.getenv("SHIELD_MAC")

# Configuration Kodi
KODI_PORT = os.getenv("KODI_PORT")
KODI_USER = os.getenv("KODI_USER")
KODI_PASS = os.getenv("KODI_PASS")

# API TMDB & TRAKT
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TRAKT_CLIENT_ID = os.getenv("TRAKT_CLIENT_ID")
TRAKT_ACCESS_TOKEN = os.getenv("TRAKT_ACCESS_TOKEN")

# --- CONFIGURATION DES PLAYERS ---
PLAYER_DEFAULT = os.getenv("PLAYER_DEFAULT", "fenlight_auto.json")
PLAYER_SELECT = os.getenv("PLAYER_SELECT", "fenlight_select.json")

# --- CONFIGURATION AUTO-PATCHER ---
FENLIGHT_REMOTE_PATH = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/sources.py"
FENLIGHT_LOCAL_TEMP = "/tmp/sources.py"
BLOCKING_CODE_SNIPPET = "return kodi_utils.notification('WARNING: External Playback Detected!')"
PATCH_CHECK_INTERVAL = 3600 

# URL de base Kodi
if SHIELD_IP and KODI_PORT:
    KODI_BASE_URL = f"http://{SHIELD_IP}:{KODI_PORT}/jsonrpc"
else:
    KODI_BASE_URL = None
    logger.critical("Configuration incomplète : SHIELD_IP ou KODI_PORT manquant.")

# ==========================================
# 2. AUTO-PATCHER
# ==========================================
def check_and_patch_fenlight():
    if not SHIELD_IP: return
    if DEBUG_MODE: logger.info(f"[PATCHER] Vérification intégrité Fen Light...")
    
    try:
        subprocess.run(["adb", "disconnect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "connect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception as e:
        if DEBUG_MODE: logger.error(f"[PATCHER] Erreur ADB Connect: {e}")
        return

    if os.path.exists(FENLIGHT_LOCAL_TEMP): os.remove(FENLIGHT_LOCAL_TEMP)
    
    try:
        res = subprocess.run(["adb", "pull", FENLIGHT_REMOTE_PATH, FENLIGHT_LOCAL_TEMP], capture_output=True, timeout=10)
        if res.returncode != 0: return 
    except: return

    try:
        with open(FENLIGHT_LOCAL_TEMP, 'r', encoding='utf-8') as f: lines = f.readlines()
        new_lines, patched = [], False
        already_patched = False
        
        for line in lines:
            if BLOCKING_CODE_SNIPPET in line:
                if line.strip().startswith("#"):
                    already_patched = True
                    new_lines.append(line)
                else:
                    logger.info("[PATCHER] Protection détectée ! Application du patch...")
                    new_lines.append("# " + line.lstrip())
                    patched = True
            else:
                new_lines.append(line)
        
        if patched:
            with open(FENLIGHT_LOCAL_TEMP, 'w', encoding='utf-8') as f: f.writelines(new_lines)
            push_res = subprocess.run(["adb", "push", FENLIGHT_LOCAL_TEMP, FENLIGHT_REMOTE_PATH], capture_output=True)
            if push_res.returncode == 0:
                logger.info("[PATCHER] SUCCÈS : Patch appliqué.")
            else:
                logger.error("[PATCHER] ÉCHEC : Impossible d'écrire sur la Shield.")
        elif already_patched and DEBUG_MODE:
            logger.info("[PATCHER] OK : Déjà patché.")
            
    except Exception as e:
        logger.error(f"[PATCHER] Erreur: {e}")

def patcher_scheduler():
    while True:
        check_and_patch_fenlight()
        time.sleep(PATCH_CHECK_INTERVAL)

# ==========================================
# 3. GESTION PUISSANCE
# ==========================================
def is_kodi_responsive():
    """Accepte 200, 401, 405 comme preuve de vie."""
    if not KODI_BASE_URL: return False
    try:
        r = requests.get(KODI_BASE_URL, timeout=2)
        if r.status_code in [200, 401, 405]: return True
    except: pass
    return False

def wake_and_start_kodi():
    if not SHIELD_IP or not SHIELD_MAC:
        logger.error("[POWER] Config manquante.")
        return False

    if is_kodi_responsive(): 
        return True

    logger.info(f"[POWER] Réveil de la Shield ({SHIELD_IP})...")
    try: send_magic_packet(SHIELD_MAC)
    except Exception as e: logger.error(f"[POWER] Erreur WoL: {e}")

    try:
        # Increase connection timeout to 5s
        subprocess.run(["adb", "connect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        # Increase wake command timeout to 5s
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(0.5)
        # Increase second wake command timeout to 5s
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
    except Exception as e: logger.error(f"[POWER] Erreur ADB: {e}")

    if is_kodi_responsive(): return True

    logger.info("[POWER] Lancement de Kodi...")
    try: 
        # Increase app launch timeout to 5s
        subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
    except: pass

    for i in range(45):
        if is_kodi_responsive(): 
            logger.info(f"[POWER] Kodi opérationnel après {i+1}s.")
            time.sleep(4)
            return True
        time.sleep(1)
    
    logger.error("[POWER] Echec : Kodi ne répond pas.")
    return False
    
# ==========================================
# 4. HELPERS
# ==========================================

def search_tmdb_movie(query, year=None, lang="fr"):
    if not TMDB_API_KEY: return None, None, None
    tmdb_lang = "fr-FR" if lang == "fr" else "en-US"
    
    base_url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": tmdb_lang}
    if year: params['year'] = year
    try:
        logger.debug(f"[TMDB] Recherche Film ({lang}): {query}")
        r = requests.get(base_url, params=params, timeout=2)
        data = r.json()
        if data.get('results'):
            res = data['results'][0]
            logger.info(f"[TMDB] Trouvé : {res['title']} ({res['id']})")
            return res['id'], res['title'], res.get('release_date', '')[:4]
        else:
            logger.warning(f"[TMDB] Aucun film trouvé pour : {query}")
    except Exception as e:
        logger.error(f"[TMDB] Erreur : {e}")
    return None, None, None

def search_tmdb_show(query, lang="fr"):
    if not TMDB_API_KEY: return None, None
    tmdb_lang = "fr-FR" if lang == "fr" else "en-US"
    
    base_url = "https://api.themoviedb.org/3/search/tv"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": tmdb_lang}
    try:
        logger.debug(f"[TMDB] Recherche Série ({lang}): {query}")
        r = requests.get(base_url, params=params, timeout=2)
        data = r.json()
        if data.get('results'):
            res = data['results'][0]
            logger.info(f"[TMDB] Trouvé : {res['name']} ({res['id']})")
            return res['id'], res['name']
        else:
            logger.warning(f"[TMDB] Aucune série trouvée pour : {query}")
    except Exception as e:
        logger.error(f"[TMDB] Erreur : {e}")
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

def get_trakt_next_episode(tmdb_show_id):
    if not TRAKT_CLIENT_ID or not TRAKT_ACCESS_TOKEN:
        logger.warning("[TRAKT] Token manquant.")
        return None, None
    
    headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': TRAKT_CLIENT_ID, 'Authorization': f'Bearer {TRAKT_ACCESS_TOKEN}'}
    try:
        r = requests.get(f"https://api.trakt.tv/search/tmdb/{tmdb_show_id}?type=show", headers=headers, timeout=2)
        results = r.json()
        if not results: return None, None
        trakt_id = results[0]['show']['ids']['trakt']
        
        r = requests.get(f"https://api.trakt.tv/shows/{trakt_id}/progress/watched", headers=headers, timeout=2)
        next_ep = r.json().get('next_episode')
        
        if next_ep:
            logger.info(f"[TRAKT] Next Up : S{next_ep['season']} E{next_ep['number']}")
            return next_ep['season'], next_ep['number']
        else:
            logger.info("[TRAKT] Pas de progression.")
    except Exception as e:
        logger.error(f"[TRAKT] Erreur : {e}")
    return None, None

# --- URL BUILDER ---
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
# 5. ROUTE FLASK
# ==========================================

@app.route('/alexa-webhook', methods=['POST'])
def alexa_handler():
    req_data = request.get_json()
    if not req_data or 'request' not in req_data:
        logger.error("Bad Request")
        return jsonify({"error": "Invalid Request"}), 400

    req_type = req_data['request']['type']
    session = req_data.get('session', {})
    attributes = session.get('attributes', {})
    
    # --- DÉTECTION LANGUE ---
    full_locale = req_data['request'].get('locale', 'fr-FR')
    lang = full_locale.split('-')[0]
    
    # LOG SYSTÉMATIQUE DE LA LANGUE (INFO)
    logger.info(f"Requête reçue ({req_type}) - Langue détectée : {lang.upper()} ({full_locale})")
    
    if DEBUG_MODE:
        logger.debug(json.dumps(req_data))

    if req_type == "LaunchRequest":
        return jsonify(build_response(get_text("launch", lang), end_session=False))

    if req_type == "IntentRequest":
        intent = req_data['request']['intent']
        intent_name = intent['name']
        slots = intent.get('slots', {})
        
        logger.info(f"Intent: {intent_name}")

        slot_source_mode = slots.get('SourceMode', {}).get('value')
        has_slot_force = True if slot_source_mode else False
        has_session_force = attributes.get('force_select', False)
        force_select = has_slot_force or has_session_force
        
        manual_msg = get_text("manual_select", lang) if force_select else ""

        # --- RESUME SHOW ---
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

        # --- PLAY MOVIE ---
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

        # --- PLAY SHOW ---
        elif intent_name == "PlayTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            season = slots.get('Season', {}).get('value')
            episode = slots.get('Episode', {}).get('value')

            if not query and attributes.get('pending_show_id'):
                tmdb_id = attributes['pending_show_id']
                title = attributes['pending_show_name']
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

                if trakt_s:
                    msg = get_text("ask_resume", lang, title, trakt_s, trakt_e)
                else:
                    msg = get_text("ask_start", lang, title)

                return jsonify(build_response(msg, end_session=False, attributes=new_attr))

        # --- REPONSES ---
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
                if attributes.get('tmdb_last_s'):
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
    response = {
        "version": "1.0",
        "sessionAttributes": attributes,
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session
        }
    }
    return response

# --- BANNER LOGGING ---
def print_startup_banner():
    masked_key = f"{TMDB_API_KEY[:4]}...{TMDB_API_KEY[-4:]}" if TMDB_API_KEY else "MISSING"
    masked_trakt = "Configured" if TRAKT_ACCESS_TOKEN else "MISSING"
    
    print("\n" + "="*50)
    print(f" KODI ALEXA CONTROLLER")
    print(f" Version : {APP_VERSION}")
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
    load_translations() 
    patcher_thread = threading.Thread(target=patcher_scheduler, daemon=True)
    patcher_thread.start()
    app.run(host='0.0.0.0', port=5000)
