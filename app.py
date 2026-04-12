# ==============================================================================
# FICHIER : app.py
# VERSION : 2.0.0
# DATE    : 2026-04-13
# AUTEUR  : Richard Perez
#
# DESCRIPTION : 
# Skill Alexa pour contrôle vocal de Kodi + WebUI de configuration.
# v2.0.0 : Interface Web moderne (Tailwind), Dashboard et Setup Trakt visuel.
# ==============================================================================

from flask import Flask, request, jsonify, render_template_string, redirect, url_for, flash
import requests
import threading
import time
import subprocess
import os
import sys
import logging
import json
import signal
import paramiko
from wakeonlan import send_magic_packet

# --- CONFIGURATION LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("KodiMiddleware")

# --- METADATA ---
APP_VERSION = "2.0.0"
APP_DATE = "2026-04-13"
APP_AUTHOR = "Richard Perez"

app = Flask(__name__)
app.secret_key = os.urandom(24) # Clé pour les sessions et messages flash

# ==========================================
# 1. CONFIGURATION & VARIABLES
# ==========================================

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
if DEBUG_MODE:
    logger.setLevel(logging.DEBUG)

DATA_DIR = "/app/data"
TOKEN_FILE = os.path.join(DATA_DIR, "trakt_tokens.json")

# API KEYS & SECURITE (ENV)
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
ALEXA_SKILL_ID = os.getenv("ALEXA_SKILL_ID") 

# SYSTEM & OS CONFIG
TARGET_OS = os.getenv("TARGET_OS", "android").lower()
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PASS = os.getenv("SSH_PASS", "libreelec")

# Réseau & Kodi
SHIELD_IP = os.getenv("SHIELD_IP")
SHIELD_MAC = os.getenv("SHIELD_MAC")
KODI_PORT = os.getenv("KODI_PORT")
KODI_USER = os.getenv("KODI_USER")
KODI_PASS = os.getenv("KODI_PASS")

# Players
PLAYER_DEFAULT = os.getenv("PLAYER_DEFAULT", "fenlight_auto.json")
PLAYER_SELECT = os.getenv("PLAYER_SELECT", "fenlight_select.json")

# Auto-Patcher Chemins
FENLIGHT_UTILS_ANDROID = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py"
FENLIGHT_UTILS_LIBREELEC = "/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py"
FENLIGHT_LOCAL_TEMP = "/tmp/kodi_utils.py"
PATCH_CHECK_INTERVAL = 3600 

if SHIELD_IP and KODI_PORT:
    KODI_BASE_URL = f"http://{SHIELD_IP}:{KODI_PORT}/jsonrpc"
else:
    KODI_BASE_URL = None

# ==========================================
# 2. GESTION DES TOKENS (LOGIQUE TRAKT)
# ==========================================

def save_trakt_token_data(access_token, refresh_token, client_id=None, client_secret=None):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    
    data = {
        "access_token": access_token, 
        "refresh_token": refresh_token, 
        "updated_at": time.time()
    }
    # Persistance des IDs si fournis via WebUI
    if client_id: data["client_id"] = client_id
    if client_secret: data["client_secret"] = client_secret

    try:
        with open(TOKEN_FILE, 'w') as f: 
            json.dump(data, f)
        logger.info("[TOKEN] Tokens sauvegardés avec succès ✅")
        return True
    except Exception as e:
        logger.error(f"[TOKEN] Erreur sauvegarde : {e}")
        return False

def load_trakt_config():
    """Charge la config depuis le fichier local ou les variables d'environnement."""
    config = {
        "access_token": os.getenv("TRAKT_ACCESS_TOKEN"),
        "refresh_token": os.getenv("TRAKT_REFRESH_TOKEN"),
        "client_id": os.getenv("TRAKT_CLIENT_ID"),
        "client_secret": os.getenv("TRAKT_CLIENT_SECRET")
    }
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                config.update(data)
        except: pass
    return config

def load_trakt_token():
    cfg = load_trakt_config()
    return cfg.get("access_token")

def refresh_trakt_token_online():
    cfg = load_trakt_config()
    if not cfg["refresh_token"] or not cfg["client_id"] or not cfg["client_secret"]:
        logger.error("[TOKEN] Impossible de renouveler : IDs manquants.")
        return None

    url = "https://api.trakt.tv/oauth/token"
    payload = {
        "refresh_token": cfg["refresh_token"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "grant_type": "refresh_token"
    }
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            save_trakt_token_data(data['access_token'], data['refresh_token'])
            return data['access_token']
        else:
            logger.error(f"[TOKEN] Echec renouvellement (Code {r.status_code})")
    except Exception as e:
        logger.error(f"[TOKEN] Exception : {e}")
    return None

# ==========================================
# 3. WEB UI (DESIGN TAILWIND)
# ==========================================

BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Cinema - Control Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0f172a; color: #f8fafc; }
        .card { background-color: #1e293b; border: 1px solid #334155; }
    </style>
</head>
<body class="min-h-screen flex flex-col">
    <nav class="p-6 border-b border-slate-800">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-2xl font-bold tracking-tight text-blue-500">🎬 MY CINEMA <span class="text-slate-500 text-sm font-normal">v{{ version }}</span></h1>
            <div class="space-x-6">
                <a href="/" class="hover:text-blue-400 transition">Dashboard</a>
                <a href="/setup" class="hover:text-blue-400 transition">Trakt Setup</a>
            </div>
        </div>
    </nav>
    <main class="container mx-auto p-8 flex-grow">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for message in messages %}
              <div class="mb-6 p-4 rounded {% if 'Error' in message or 'Erreur' in message %}bg-red-900/50 border border-red-500 text-red-200{% else %}bg-green-900/50 border border-green-500 text-green-200{% endif %}">
                {{ message }}
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>
    <footer class="p-8 border-t border-slate-800 text-center text-slate-500 text-sm">
        My Cinema &copy; 2026 - Vibe Coding Experiment
    </footer>
</body>
</html>
"""

DASHBOARD_HTML = """
{% extends "base" %}
{% block content %}
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="card p-6 rounded-xl">
        <h2 class="text-slate-400 text-sm uppercase font-semibold mb-2">Kodi Status</h2>
        <div class="flex items-center space-x-3">
            <div class="h-3 w-3 rounded-full {% if kodi_ok %}bg-green-500{% else %}bg-red-500{% endif %}"></div>
            <span class="text-xl font-medium">{{ shield_ip }}</span>
        </div>
        <p class="text-slate-500 text-xs mt-4">Target OS: {{ target_os.upper() }}</p>
    </div>
    <div class="card p-6 rounded-xl">
        <h2 class="text-slate-400 text-sm uppercase font-semibold mb-2">TMDB API</h2>
        <div class="flex items-center space-x-3">
            <div class="h-3 w-3 rounded-full {% if tmdb_ok %}bg-green-500{% else %}bg-red-500{% endif %}"></div>
            <span class="text-xl font-medium">TheMovieDB</span>
        </div>
        <p class="text-slate-500 text-xs mt-4">Key: {{ tmdb_key_masked }}</p>
    </div>
    <div class="card p-6 rounded-xl">
        <h2 class="text-slate-400 text-sm uppercase font-semibold mb-2">Trakt.tv Auth</h2>
        <div class="flex items-center space-x-3">
            <div class="h-3 w-3 rounded-full {% if trakt_ok %}bg-green-500{% else %}bg-red-500{% endif %}"></div>
            <span class="text-xl font-medium">Account Sync</span>
        </div>
        <p class="text-slate-500 text-xs mt-4">Token: {% if trakt_ok %}Active{% else %}Missing{% endif %}</p>
    </div>
</div>
{% endblock %}
"""

SETUP_HTML = """
{% extends "base" %}
{% block content %}
<div class="max-w-2xl mx-auto card p-8 rounded-xl">
    <h2 class="text-2xl font-bold mb-2">Trakt Authentication</h2>
    <p class="text-slate-400 mb-8 text-sm">Follow these steps to generate your access tokens.</p>
    <form method="POST" class="space-y-6">
        <div>
            <label class="block text-sm font-medium text-slate-300 mb-2">1. Client ID</label>
            <input type="text" name="client_id" value="{{ cfg.client_id or '' }}" required
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none">
        </div>
        <div>
            <label class="block text-sm font-medium text-slate-300 mb-2">2. Client Secret</label>
            <input type="password" name="client_secret" value="{{ cfg.client_secret or '' }}" required
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none">
        </div>
        <div class="pt-4 border-t border-slate-700">
            <label class="block text-sm font-medium text-slate-300 mb-2">3. PIN Code</label>
            <div class="flex space-x-4 mb-2">
                <input type="text" name="pin_code" placeholder="Paste PIN here" required
                    class="flex-grow bg-slate-900 border border-slate-700 rounded-lg p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none">
                <button type="button" onclick="window.open('https://trakt.tv/oauth/authorize?response_type=code&client_id=' + document.getElementsByName('client_id')[0].value + '&redirect_uri=urn:ietf:wg:oauth:2.0:oob')"
                    class="bg-slate-700 hover:bg-slate-600 px-4 rounded-lg transition text-sm">Get PIN</button>
            </div>
        </div>
        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-4 rounded-lg transition">GENERATE TOKENS</button>
    </form>
</div>
{% endblock %}
"""

# ==========================================
# 4. ROUTES FLASK (WEB & API)
# ==========================================

@app.route('/')
def dashboard():
    kodi_ok = is_kodi_responsive()
    tmdb_ok = False
    try:
        r = requests.get(f"https://api.themoviedb.org/3/movie/19995?api_key={TMDB_API_KEY}", timeout=3)
        tmdb_ok = (r.status_code == 200)
    except: pass
    cfg = load_trakt_config()
    return render_template_string(DASHBOARD_HTML, base=BASE_HTML, version=APP_VERSION, kodi_ok=kodi_ok, shield_ip=SHIELD_IP, target_os=TARGET_OS, tmdb_ok=tmdb_ok, tmdb_key_masked=f"{TMDB_API_KEY[:4]}...{TMDB_API_KEY[-4:]}" if TMDB_API_KEY else "MISSING", trakt_ok=bool(cfg["access_token"]))

@app.route('/setup', methods=['GET', 'POST'])
def trakt_setup():
    if request.method == 'POST':
        c_id = request.form.get('client_id')
        c_secret = request.form.get('client_secret')
        pin = request.form.get('pin_code')
        url = "https://api.trakt.tv/oauth/token"
        payload = {"code": pin, "client_id": c_id, "client_secret": c_secret, "redirect_uri": "urn:ietf:wg:oauth:2.0:oob", "grant_type": "authorization_code"}
        try:
            r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                save_trakt_token_data(data['access_token'], data['refresh_token'], c_id, c_secret)
                flash("Success! Tokens generated.")
                return redirect(url_for('dashboard'))
            else: flash(f"Trakt Error: {r.text}")
        except Exception as e: flash(f"Error: {str(e)}")
    return render_template_string(SETUP_HTML, base=BASE_HTML, version=APP_VERSION, cfg=load_trakt_config())

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "version": APP_VERSION}), 200

# ==========================================
# 5. TRADUCTIONS & PATCHER (v1.9.0)
# ==========================================

TRANSLATIONS = {}

def load_translations():
    global TRANSLATIONS
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'translations.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            TRANSLATIONS = json.load(f)
    except Exception as e:
        logger.error(f"Erreur translations.json : {e}")

def get_text(key, lang="fr", *args):
    target_lang = lang if lang in TRANSLATIONS else "fr"
    text_template = TRANSLATIONS.get(target_lang, {}).get(key, "")
    if args and text_template:
        try: return text_template.format(*args)
        except: return text_template
    return text_template

def check_and_patch_fenlight():
    if not SHIELD_IP: return
    content = ""
    ssh = None
    sftp = None
    try:
        if TARGET_OS == "android":
            subprocess.run(["adb", "connect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            res = subprocess.run(["adb", "pull", FENLIGHT_UTILS_ANDROID, FENLIGHT_LOCAL_TEMP], capture_output=True)
            if res.returncode != 0: return 
            with open(FENLIGHT_LOCAL_TEMP, 'r', encoding='utf-8') as f: content = f.read()
        elif TARGET_OS == "libreelec":
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SHIELD_IP, username=SSH_USER, password=SSH_PASS, timeout=5)
            sftp = ssh.open_sftp()
            with sftp.file(FENLIGHT_UTILS_LIBREELEC, 'r') as f: content = f.read().decode('utf-8')
    except: return

    T1_O = "if mode == 'playback.%s' % playback_key():"
    T1_P = "if True: # mode == 'playback.%s' % playback_key():"
    T2_O = "if not playback_key() in params:"
    T2_P = "if False: # not playback_key() in params:"
    
    if T1_P in content and T2_P in content:
        if ssh: ssh.close()
        return

    new_content = content.replace(T1_O, T1_P).replace(T2_O, T2_P)
    try:
        if TARGET_OS == "android":
            with open(FENLIGHT_LOCAL_TEMP, 'w', encoding='utf-8') as f: f.write(new_content)
            subprocess.run(["adb", "push", FENLIGHT_LOCAL_TEMP, FENLIGHT_UTILS_ANDROID])
        elif TARGET_OS == "libreelec":
            with sftp.file(FENLIGHT_UTILS_LIBREELEC, 'w') as f: f.write(new_content)
    finally:
        if ssh: ssh.close()

def patcher_scheduler():
    while True:
        check_and_patch_fenlight()
        time.sleep(PATCH_CHECK_INTERVAL)

# ==========================================
# 6. GESTION PUISSANCE & KODI HELPERS
# ==========================================

def is_kodi_responsive():
    if not KODI_BASE_URL: return False
    try:
        r = requests.get(KODI_BASE_URL, timeout=2)
        return r.status_code in [200, 401, 405]
    except: return False

def wake_and_start_kodi():
    if not SHIELD_IP or not SHIELD_MAC: return False
    if is_kodi_responsive(): return True
    if TARGET_OS == "android":
        send_magic_packet(SHIELD_MAC)
        subprocess.run(["adb", "connect", SHIELD_IP], timeout=5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"])
        time.sleep(2)
        if is_kodi_responsive(): return True
        subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"])
        for _ in range(30):
            if is_kodi_responsive(): return True
            time.sleep(1)
    return is_kodi_responsive()

def get_kodi_active_player():
    payload = {"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1}
    try:
        r = requests.post(KODI_BASE_URL, json=payload, auth=(KODI_USER, KODI_PASS), timeout=3)
        data = r.json().get('result', [])
        for p in data:
            if p.get('type') == 'video': return p.get('playerid')
    except: pass
    return None

def search_tmdb_movie(query, year=None, lang="fr"):
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "fr-FR" if lang=="fr" else "en-US"}
    if year: params['year'] = year
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=3)
        res = r.json().get('results', [])[0]
        return res['id'], res['title'], res.get('release_date', '')[:4]
    except: return None, None, None

def get_playback_url(tmdb_id, m_type, s=None, e=None, select=False):
    p = PLAYER_SELECT if select else PLAYER_DEFAULT
    base = f"plugin://plugin.video.themoviedb.helper/?info=play&player={p}&tmdb_id={tmdb_id}"
    if m_type == "movie": return f"{base}&type=movie"
    return f"{base}&season={s}&episode={e}&type=episode"

def worker_process(url):
    if wake_and_start_kodi():
        payload = {"jsonrpc": "2.0", "method": "Player.Open", "params": {"item": {"file": url}}, "id": 1}
        requests.post(KODI_BASE_URL, json=payload, auth=(KODI_USER, KODI_PASS), timeout=5)

# ==========================================
# 7. ALEXA WEBHOOK HANDLER
# ==========================================

@app.route('/alexa-webhook', methods=['POST'])
def alexa_handler():
    req = request.get_json()
    if ALEXA_SKILL_ID:
        incoming_id = req.get('session', {}).get('application', {}).get('applicationId')
        if incoming_id != ALEXA_SKILL_ID: return jsonify({"error": "Forbidden"}), 403

    lang = req['request'].get('locale', 'fr-FR').split('-')[0]
    r_type = req['request']['type']

    if r_type == "LaunchRequest":
        return jsonify(build_response(get_text("launch", lang), False))

    if r_type == "IntentRequest":
        intent = req['request']['intent']['name']
        slots = req['request']['intent'].get('slots', {})
        
        if intent == "PlayMovieIntent":
            q = slots.get('MovieName', {}).get('value')
            m_id, title, year = search_tmdb_movie(q, lang=lang)
            if m_id:
                url = get_playback_url(m_id, "movie")
                threading.Thread(target=worker_process, args=(url,)).start()
                return jsonify(build_response(get_text("launch_movie", lang, title, year, "")))

    return jsonify(build_response(get_text("not_understood", lang)))

def build_response(text, end=True, attr={}):
    return {"version": "1.0", "sessionAttributes": attr, "response": {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end}}

# ==========================================
# 8. STARTUP
# ==========================================

if __name__ == '__main__':
    load_translations()
    threading.Thread(target=patcher_scheduler, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
