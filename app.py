# ==============================================================================
# FICHIER : app.py
# VERSION : 2.1.0
# DATE    : 2026-04-13
# AUTEUR  : Richard Perez (richard@perez-mail.fr)
#
# DESCRIPTION : 
# Skill Alexa pour contrôle vocal de Kodi.
# UPDATE v2.1.0 : Configuration dynamique depuis l'UI Web.
# UPDATE v2.0.0 : Ajout du Web UI Control Panel (Dashboard + Trakt Setup).
# UPDATE v1.9.0 : Support LibreELEC / Raspberry Pi (SSH) + Android TV (ADB).
# ==============================================================================

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
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

# ==========================================
# 1. DOSSIERS & LOGGING
# ==========================================

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

# --- METADATA ---
APP_VERSION = "2.1.0"
APP_DATE = "2026-04-13"
APP_AUTHOR = "Richard Perez"

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ==========================================
# 2. GESTION DE LA CONFIGURATION (Dynamique)
# ==========================================

def get_app_config():
    """Charge la configuration depuis le fichier JSON, ou utilise les ENV par défaut."""
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
                # Remplace les valeurs par celles du fichier si elles existent
                for k, v in file_conf.items():
                    config[k] = v
        except Exception as e:
            logger.error(f"[CONFIG] Erreur lecture config.json : {e}")
            
    return config

def save_app_config(new_config):
    """Sauvegarde la configuration dans le fichier JSON persistant."""
    try:
        with open(APP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=4)
        logger.info("[CONFIG] Configuration globale sauvegardée avec succès.")
        return True
    except Exception as e:
        logger.error(f"[CONFIG] Erreur sauvegarde config.json : {e}")
        return False

def get_kodi_url(conf):
    ip = conf.get("SHIELD_IP")
    port = conf.get("KODI_PORT")
    if ip and port:
        return f"http://{ip}:{port}/jsonrpc"
    return None

# ==========================================
# 3. GESTION DES TOKENS (TRAKT)
# ==========================================

def save_trakt_token_data(access_token, refresh_token, client_id=None, client_secret=None):
    data = {
        "access_token": access_token, 
        "refresh_token": refresh_token, 
        "updated_at": time.time()
    }
    if client_id: data["client_id"] = client_id
    if client_secret: data["client_secret"] = client_secret

    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f: 
            json.dump(data, f)
        logger.info("[TOKEN] Tokens sauvegardés dans trakt_tokens.json ✅")
        return True
    except Exception as e:
        logger.error(f"[TOKEN] Impossible de sauvegarder les tokens : {e}")
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
                for key in config.keys():
                    if data.get(key): config[key] = data[key]
        except Exception as e:
            logger.error(f"[TOKEN] Erreur lecture fichier token : {e}")
    return config

def load_trakt_token():
    cfg = load_trakt_config()
    if cfg["access_token"]:
        return cfg["access_token"]
    logger.error("[TOKEN] Aucun token disponible (ni fichier, ni ENV).")
    return None

def refresh_trakt_token_online():
    logger.info("[TOKEN] Tentative de renouvellement du token...")
    cfg = load_trakt_config()
    
    if not cfg["refresh_token"] or not cfg["client_secret"] or not cfg["client_id"]:
        logger.error("[TOKEN] Impossible de renouveler : IDs ou Refresh Token manquant.")
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
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            save_trakt_token_data(data['access_token'], data['refresh_token'], cfg["client_id"], cfg["client_secret"])
            return data['access_token']
        else:
            logger.error(f"[TOKEN] Echec renouvellement (Code {r.status_code}): {r.text}")
    except Exception as e:
        logger.error(f"[TOKEN] Exception lors du renouvellement : {e}")
    return None

# ==========================================
# 4. ROUTES FLASK (WEB UI)
# ==========================================

@app.route('/')
def dashboard():
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    kodi_ok = is_kodi_responsive()
    
    tmdb_ok = False
    tmdb_key = conf.get('TMDB_API_KEY')
    if tmdb_key:
        try:
            r = requests.get(f"https://api.themoviedb.org/3/movie/19995?api_key={tmdb_key}", timeout=3)
            tmdb_ok = (r.status_code == 200)
        except Exception as e: 
            logger.warning(f"[DASHBOARD] Vérification TMDB échouée: {e}")
    
    trakt_cfg = load_trakt_config()
    
    return render_template(
        'dashboard.html', 
        version=APP_VERSION, 
        device_ok=device_ok,
        kodi_ok=kodi_ok, 
        shield_ip=conf.get('SHIELD_IP') or "Non configuré", 
        target_os=conf.get('TARGET_OS'), 
        tmdb_ok=tmdb_ok, 
        tmdb_key_masked=f"{tmdb_key[:4]}...{tmdb_key[-4:]}" if tmdb_key else "MISSING", 
        trakt_ok=bool(trakt_cfg.get("access_token")),
        p_def=conf.get('PLAYER_DEFAULT'),
        p_sel=conf.get('PLAYER_SELECT'),
        skill_id=conf.get('ALEXA_SKILL_ID')
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    conf = get_app_config()
    if request.method == 'POST':
        new_conf = {
            "TMDB_API_KEY": request.form.get("TMDB_API_KEY", "").strip(),
            "ALEXA_SKILL_ID": request.form.get("ALEXA_SKILL_ID", "").strip(),
            "TARGET_OS": request.form.get("TARGET_OS", "android").lower(),
            "SSH_USER": request.form.get("SSH_USER", "").strip(),
            "SSH_PASS": request.form.get("SSH_PASS", "").strip(),
            "SHIELD_IP": request.form.get("SHIELD_IP", "").strip(),
            "SHIELD_MAC": request.form.get("SHIELD_MAC", "").strip(),
            "KODI_PORT": request.form.get("KODI_PORT", "8080").strip(),
            "KODI_USER": request.form.get("KODI_USER", "").strip(),
            "KODI_PASS": request.form.get("KODI_PASS", "").strip(),
            "PLAYER_DEFAULT": request.form.get("PLAYER_DEFAULT", "fenlight_auto.json").strip(),
            "PLAYER_SELECT": request.form.get("PLAYER_SELECT", "fenlight_select.json").strip()
        }
        if save_app_config(new_conf):
            flash("Configuration sauvegardée avec succès !", "success")
        else:
            flash("Erreur lors de la sauvegarde de la configuration.", "error")
        return redirect(url_for('settings'))
    
    return render_template('settings.html', version=APP_VERSION, conf=conf)

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
        
    cfg = load_trakt_config()
    return render_template('setup.html', version=APP_VERSION, cfg=cfg)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "version": APP_VERSION}), 200

# ==========================================
# ROUTES DIAGNOSTIC MANUEL (Dashboard)
# ==========================================

@app.route('/wake-device', methods=['POST'])
def wake_device_route():
    logger.info("[WEB] Commande manuelle : Wake Device.")
    conf = get_app_config()
    mac = conf.get("SHIELD_MAC")
    ip = conf.get("SHIELD_IP")
    target = conf.get("TARGET_OS")

    if mac:
        try: send_magic_packet(mac)
        except Exception as e: logger.warning(f"[POWER] Erreur WoL: {e}")
    if target == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        except Exception as e: logger.warning(f"[POWER] Erreur ADB WAKEUP: {e}")
    flash("Signal de réveil envoyé à l'appareil.")
    return redirect(url_for('dashboard'))

@app.route('/shutdown-device', methods=['POST'])
def shutdown_device_route():
    logger.info("[WEB] Commande manuelle : Shutdown/Sleep Device.")
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    target = conf.get("TARGET_OS")

    if target == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "input", "keyevent", "SLEEP"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Commande de mise en veille envoyée à l'appareil Android.")
        except Exception as e:
            logger.error(f"[POWER] Erreur ADB SLEEP: {e}")
            flash(f"Erreur de mise en veille ADB : {e}")
    elif target == "libreelec" and ip:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            ssh.exec_command("poweroff")
            ssh.close()
            flash("Commande d'extinction envoyée via SSH (LibreELEC).")
        except Exception as e:
            logger.error(f"[POWER] Erreur SSH SHUTDOWN: {e}")
            flash(f"Erreur d'extinction SSH : {e}")
    return redirect(url_for('dashboard'))

@app.route('/start-kodi', methods=['POST'])
def start_kodi_route():
    logger.info("[WEB] Commande manuelle : Start Kodi.")
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    if conf.get("TARGET_OS") == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Commande de lancement de Kodi envoyée via ADB.")
        except Exception as e:
            logger.warning(f"[POWER] Erreur ADB START KODI: {e}")
            flash(f"Erreur ADB lors du lancement : {e}")
    else:
        flash("Start Kodi est géré par l'OS sur LibreELEC.")
    return redirect(url_for('dashboard'))

@app.route('/stop-kodi', methods=['POST'])
def stop_kodi_route():
    logger.info("[WEB] Commande manuelle : Stop Kodi.")
    conf = get_app_config()
    kodi_url = get_kodi_url(conf)
    ip = conf.get("SHIELD_IP")
    quit_success = False
    
    if is_kodi_responsive():
        try:
            payload = {"jsonrpc": "2.0", "method": "Application.Quit", "id": 1}
            user, pwd = conf.get("KODI_USER"), conf.get("KODI_PASS")
            auth = (user, pwd) if user and pwd else None
            r = requests.post(kodi_url, json=payload, auth=auth, timeout=3)
            if r.status_code == 200:
                quit_success = True
                flash("Kodi s'est arrêté proprement (JSON-RPC).")
        except requests.exceptions.RequestException:
            logger.warning("[POWER] Impossible de joindre Kodi via JSON-RPC pour l'arrêt.")
        except Exception as e:
            logger.warning(f"[POWER] Erreur inattendue JSON-RPC Quit: {e}")
    else:
        logger.info("[POWER] Kodi ne répond pas, passage au fallback ADB.")

    if conf.get("TARGET_OS") == "android" and not quit_success and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "am", "force-stop", "org.xbmc.kodi"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Commande d'arrêt envoyée via ADB.")
        except Exception as e:
            logger.error(f"[POWER] Erreur ADB FORCE-STOP: {e}")
            flash(f"Erreur lors de la fermeture de Kodi : {e}")
    elif not quit_success:
        flash("Impossible de fermer Kodi de force (OS non-Android ou hors ligne).")
        
    return redirect(url_for('dashboard'))

@app.route('/test-connection', methods=['POST'])
def test_connection_route():
    logger.info("[WEB] Commande manuelle : Test Connection (ADB/SSH).")
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    target = conf.get("TARGET_OS")

    if not ip:
        flash("Veuillez d'abord configurer une IP dans les Paramètres.")
        return redirect(url_for('dashboard'))

    if target == "android":
        try:
            subprocess.run(["adb", "connect", ip], capture_output=True, timeout=5)
            res = subprocess.run(["adb", "shell", "echo", "ADB_OK"], capture_output=True, text=True, timeout=5)
            if "ADB_OK" in res.stdout:
                flash("Test de connexion ADB réussi ✅")
            else:
                flash(f"Échec de la connexion ADB ❌ : {res.stderr.strip() or 'Pas de réponse.'}")
        except Exception as e:
            logger.warning(f"[TEST] Erreur lors du test ADB : {e}")
            flash(f"Erreur lors de la tentative de connexion ADB : {e}")
            
    elif target == "libreelec":
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            stdin, stdout, stderr = ssh.exec_command("echo SSH_OK")
            out = stdout.read().decode('utf-8').strip()
            ssh.close()
            if out == "SSH_OK":
                flash("Test de connexion SSH réussi ✅")
            else:
                err = stderr.read().decode('utf-8').strip()
                flash(f"Échec de la connexion SSH ❌ : {err or 'Réponse inattendue.'}")
        except Exception as e:
            logger.warning(f"[TEST] Erreur lors du test SSH : {e}")
            flash(f"Erreur lors de la tentative de connexion SSH : {e}")
            
    return redirect(url_for('dashboard'))

@app.route('/api/logs', methods=['GET'])
def api_logs():
    try:
        if not os.path.exists(LOG_FILE):
            return jsonify({"logs": "Aucun log disponible pour le moment."})
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-150:]
        return jsonify({"logs": "".join(last_lines)})
    except Exception as e:
        return jsonify({"logs": f"Erreur lors de la lecture des logs : {e}"})

# ==========================================
# 5. TRADUCTIONS & PATCHER
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
    conf = get_app_config()
    SHIELD_IP = conf.get("SHIELD_IP")
    TARGET_OS = conf.get("TARGET_OS")
    if not SHIELD_IP: return
    if DEBUG_MODE: logger.info(f"[PATCHER] Vérification intégrité Fen Light (OS: {TARGET_OS})...")
    
    content = ""
    ssh = None
    sftp = None
    
    try:
        if TARGET_OS == "android":
            subprocess.run(["adb", "disconnect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["adb", "connect", SHIELD_IP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if os.path.exists(FENLIGHT_LOCAL_TEMP): os.remove(FENLIGHT_LOCAL_TEMP)
            
            res = subprocess.run(["adb", "pull", "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", FENLIGHT_LOCAL_TEMP], capture_output=True, timeout=10)
            if res.returncode != 0: return 
            
            with open(FENLIGHT_LOCAL_TEMP, 'r', encoding='utf-8') as f: 
                content = f.read()

        elif TARGET_OS == "libreelec":
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SHIELD_IP, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            sftp = ssh.open_sftp()
            
            with sftp.file("/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", 'r') as f:
                content = f.read().decode('utf-8')
    except Exception as e:
        if DEBUG_MODE: logger.error(f"[PATCHER] Erreur de connexion/lecture ({TARGET_OS}): {e}")
        return

    TARGET_1_ORIG = "if mode == 'playback.%s' % playback_key():"
    TARGET_1_PATCH = "if True: # mode == 'playback.%s' % playback_key():"
    TARGET_2_ORIG = "if not playback_key() in params:"
    TARGET_2_PATCH = "if False: # not playback_key() in params:"
    
    has_patch_1 = TARGET_1_PATCH in content
    has_patch_2 = TARGET_2_PATCH in content
    has_orig_1 = TARGET_1_ORIG in content
    has_orig_2 = TARGET_2_ORIG in content
    
    if has_patch_1 and has_patch_2:
        if DEBUG_MODE: logger.info("[PATCHER] OK : Fichier déjà patché.")
        if TARGET_OS == "libreelec" and sftp and ssh:
            sftp.close()
            ssh.close()
        return

    if not has_orig_1 and not has_patch_1:
         logger.warning("[PATCHER] ALERTE : Code 'player_check' introuvable dans le fichier local !")
         return
    if not has_orig_2 and not has_patch_2:
         logger.warning("[PATCHER] ALERTE : Code 'external_playback_check' introuvable dans le fichier local !")
         return

    new_content = content
    patched = False
    
    if has_orig_1:
        new_content = new_content.replace(TARGET_1_ORIG, TARGET_1_PATCH)
        patched = True
    if has_orig_2:
        new_content = new_content.replace(TARGET_2_ORIG, TARGET_2_PATCH)
        patched = True
    
    if patched:
        try:
            if TARGET_OS == "android":
                with open(FENLIGHT_LOCAL_TEMP, 'w', encoding='utf-8') as f: 
                    f.write(new_content)
                push_res = subprocess.run(["adb", "push", FENLIGHT_LOCAL_TEMP, "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py"], capture_output=True)
                if push_res.returncode == 0: 
                    logger.info("[PATCHER] SUCCÈS : Patchs appliqués via ADB.")
                else: 
                    logger.error("[PATCHER] ÉCHEC : Impossible d'écrire sur la Shield.")
                    
            elif TARGET_OS == "libreelec":
                with sftp.file("/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", 'w') as f:
                    f.write(new_content)
                logger.info("[PATCHER] SUCCÈS : Patchs appliqués via SSH.")
        except Exception as e:
            logger.error(f"[PATCHER] Erreur lors de l'envoi du fichier patché ({TARGET_OS}): {e}")
        finally:
            if TARGET_OS == "libreelec" and sftp and ssh:
                sftp.close()
                ssh.close()

def patcher_scheduler():
    while True:
        check_and_patch_fenlight()
        time.sleep(PATCH_CHECK_INTERVAL)

# ==========================================
# 6. GESTION PUISSANCE
# ==========================================

def is_device_online(ip):
    if not ip: return False
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception as e:
        if DEBUG_MODE: logger.debug(f"[PING] Erreur ping: {e}")
        return False

def is_kodi_responsive():
    conf = get_app_config()
    kodi_url = get_kodi_url(conf)
    if not kodi_url: return False
    try:
        r = requests.get(kodi_url, timeout=2)
        if r.status_code in [200, 401, 405]: return True
    except Exception as e: 
        if DEBUG_MODE: logger.debug(f"[KODI] Non responsive: {e}")
    return False

def wake_and_start_kodi():
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    mac = conf.get("SHIELD_MAC")
    target = conf.get("TARGET_OS")
    
    if not ip: return False
    if is_kodi_responsive(): return True
    
    if target == "libreelec":
        logger.error(f"[POWER] Kodi sur LibreELEC ({ip}) ne répond pas. Vérifiez que l'appareil est allumé.")
        return False

    logger.info(f"[POWER] Réveil de l'appareil Android ({ip})...")
    if mac:
        try: send_magic_packet(mac)
        except Exception as e: logger.warning(f"[POWER] Erreur Wake-on-LAN: {e}")
    try:
        subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(0.5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
    except Exception as e: logger.warning(f"[POWER] Erreur réveil ADB: {e}")
    
    if is_kodi_responsive(): return True
    
    try: subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
    except Exception as e: logger.warning(f"[POWER] Erreur démarrage Kodi ADB: {e}")
    for i in range(45):
        if is_kodi_responsive(): 
            time.sleep(4)
            return True
        time.sleep(1)
    return False

# ==========================================
# 7. HELPERS (KODI CONTROL & TMDB)
# ==========================================
def verify_api_status():
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    logger.info("--- VÉRIFICATION DES ACCÈS API ---")
    if not tmdb_key: logger.error("[API] TMDB_API_KEY manquant !")
    else:
        try:
            r = requests.get(f"https://api.themoviedb.org/3/movie/19995?api_key={tmdb_key}", timeout=5)
            if r.status_code == 200: logger.info("[API] TMDB : OK ✅")
            else: logger.warning(f"[API] TMDB : Erreur ({r.status_code})")
        except Exception as e: logger.error(f"[API] TMDB : Injoignable ({e})")

    cfg = load_trakt_config()
    token = cfg.get("access_token")
    if not token or not cfg.get("client_id"): logger.error("[API] TRAKT : Token manquant !")
    else:
        headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': cfg["client_id"], 'Authorization': f'Bearer {token}'}
        try:
            r = requests.get("https://api.trakt.tv/users/settings", headers=headers, timeout=5)
            if r.status_code == 200: logger.info("[API] TRAKT : Token OK ✅")
            elif r.status_code == 401:
                logger.warning("[API] TRAKT : Token expiré. Renouvellement...")
                if refresh_trakt_token_online(): logger.info("[API] TRAKT : Renouvellement OK ✅")
                else: logger.critical("[API] TRAKT : Echec renouvellement ❌")
            else: logger.warning(f"[API] TRAKT : Statut {r.status_code}")
        except Exception as e: logger.error(f"[API] TRAKT : Injoignable ({e})")
    logger.info("-" * 30)

def get_kodi_active_player():
    conf = get_app_config()
    kodi_url = get_kodi_url(conf)
    if not kodi_url: return None
    payload = {"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1}
    try:
        user, pwd = conf.get("KODI_USER"), conf.get("KODI_PASS")
        auth = (user, pwd) if user and pwd else None
        r = requests.post(kodi_url, json=payload, auth=auth, timeout=3)
        data = r.json().get('result', [])
        for player in data:
            if player.get('type') == 'video':
                return player.get('playerid')
    except Exception as e: logger.error(f"[KODI] Impossible de récupérer le lecteur actif: {e}")
    return None

def get_kodi_player_item(player_id):
    conf = get_app_config()
    kodi_url = get_kodi_url(conf)
    if not kodi_url: return None
    payload = {
        "jsonrpc": "2.0", 
        "method": "Player.GetItem", 
        "params": { 
            "properties": ["title", "year", "season", "episode", "showtitle"], 
            "playerid": player_id 
        }, 
        "id": 1
    }
    try:
        user, pwd = conf.get("KODI_USER"), conf.get("KODI_PASS")
        auth = (user, pwd) if user and pwd else None
        r = requests.post(kodi_url, json=payload, auth=auth, timeout=3)
        return r.json().get('result', {}).get('item')
    except Exception as e: logger.error(f"[KODI] Impossible de récupérer l'élément en cours: {e}")
    return None

def stop_kodi_playback(player_id):
    conf = get_app_config()
    kodi_url = get_kodi_url(conf)
    if not kodi_url: return
    payload = {"jsonrpc": "2.0", "method": "Player.Stop", "params": {"playerid": player_id}, "id": 1}
    try:
        user, pwd = conf.get("KODI_USER"), conf.get("KODI_PASS")
        auth = (user, pwd) if user and pwd else None
        requests.post(kodi_url, json=payload, auth=auth, timeout=3)
        logger.info("[KODI] Lecture arrêtée.")
    except Exception as e: logger.error(f"[KODI] Impossible d'arrêter la lecture: {e}")

def get_trakt_next_episode(tmdb_show_id):
    current_token = load_trakt_token()
    cfg = load_trakt_config()
    client_id = cfg.get("client_id")
    if not client_id or not current_token: return None, None
    headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': client_id, 'Authorization': f'Bearer {current_token}'}
    
    def make_request(url):
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 401:
            new_t = refresh_trakt_token_online()
            if new_t:
                headers['Authorization'] = f'Bearer {new_t}'
                return requests.get(url, headers=headers, timeout=2)
        return r

    try:
        r = make_request(f"https://api.trakt.tv/search/tmdb/{tmdb_show_id}?type=show")
        if r.status_code != 200: return None, None
        results = r.json()
        if not results: return None, None
        trakt_id = results[0]['show']['ids']['trakt']
        
        r = make_request(f"https://api.trakt.tv/shows/{trakt_id}/progress/watched")
        if r.status_code != 200: return None, None
        next_ep = r.json().get('next_episode')
        if next_ep: return next_ep['season'], next_ep['number']
    except Exception as e: logger.error(f"[TRAKT] Erreur lors de la recherche du prochain épisode: {e}")
    return None, None

def search_tmdb_movie(query, year=None, lang="fr"):
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None, None
    tmdb_lang = "fr-FR" if lang == "fr" else "en-US"
    params = {"api_key": tmdb_key, "query": query, "language": tmdb_lang}
    if year: params['year'] = year
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=2)
        data = r.json()
        if data.get('results'):
            res = data['results'][0]
            return res['id'], res['title'], res.get('release_date', '')[:4]
    except Exception as e: logger.error(f"[TMDB] Erreur recherche film: {e}")
    return None, None, None

def search_tmdb_show(query, lang="fr"):
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None
    tmdb_lang = "fr-FR" if lang == "fr" else "en-US"
    params = {"api_key": tmdb_key, "query": query, "language": tmdb_lang}
    try:
        r = requests.get("https://api.themoviedb.org/3/search/tv", params=params, timeout=2)
        data = r.json()
        if data.get('results'):
            res = data['results'][0]
            return res['id'], res['name']
    except Exception as e: logger.error(f"[TMDB] Erreur recherche série: {e}")
    return None, None

def check_episode_exists(tmdb_id, season, episode):
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return False
    try:
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}", params={"api_key": tmdb_key}, timeout=2)
        return r.status_code == 200
    except Exception as e: 
        logger.error(f"[TMDB] Erreur vérification épisode: {e}")
        return True

def get_tmdb_last_aired(tmdb_id):
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None
    try:
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", params={"api_key": tmdb_key}, timeout=2)
        last_ep = r.json().get('last_episode_to_air')
        if last_ep: return last_ep['season_number'], last_ep['episode_number']
    except Exception as e: logger.error(f"[TMDB] Erreur vérification dernier épisode: {e}")
    return None, None

def get_playback_url(tmdb_id, media_type, season=None, episode=None, force_select=False):
    conf = get_app_config()
    p_def = conf.get("PLAYER_DEFAULT") or "fenlight_auto.json"
    p_sel = conf.get("PLAYER_SELECT") or "fenlight_select.json"
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
    conf = get_app_config()
    kodi_url = get_kodi_url(conf)
    if kodi_url:
        payload = {"jsonrpc": "2.0", "method": "Player.Open", "params": {"item": {"file": plugin_url}}, "id": 1}
        try:
            user, pwd = conf.get("KODI_USER"), conf.get("KODI_PASS")
            auth = (user, pwd) if user and pwd else None
            requests.post(kodi_url, json=payload, auth=auth, timeout=5)
        except Exception as e: logger.error(f"[KODI] Erreur ouverture lecteur: {e}")
    logger.info(">>> FIN PROCESSUS LECTURE")

def change_source_worker(player_id, next_url):
    stop_kodi_playback(player_id)
    time.sleep(2)
    worker_process(next_url)

# ==========================================
# 8. ALEXA WEBHOOK ROUTE
# ==========================================

@app.route('/alexa-webhook', methods=['POST'])
def alexa_handler():
    req_data = request.get_json()
    if not req_data or 'request' not in req_data: return jsonify({"error": "Invalid Request"}), 400

    conf = get_app_config()
    skill_id = conf.get("ALEXA_SKILL_ID")

    # --- SÉCURITÉ : Validation de l'ID de la Skill Alexa ---
    if skill_id:
        try:
            session_app_id = req_data.get('session', {}).get('application', {}).get('applicationId')
            context_app_id = req_data.get('context', {}).get('System', {}).get('application', {}).get('applicationId')
            incoming_app_id = session_app_id or context_app_id
            
            if incoming_app_id != skill_id:
                logger.warning(f"[SÉCURITÉ] ALERTE: Requête rejetée. Skill ID non reconnu ({incoming_app_id})")
                return jsonify({"error": "Forbidden"}), 403
        except Exception as e:
            logger.error(f"[SÉCURITÉ] Erreur lors de l'extraction de l'ID Alexa : {e}")
            return jsonify({"error": "Forbidden"}), 403

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

        if intent_name == "TriggerPatcherIntent":
            threading.Thread(target=check_and_patch_fenlight).start()
            return jsonify(build_response(get_text("patcher_triggered", lang)))

        elif intent_name == "ChangeSourceIntent":
            if not is_kodi_responsive():
                return jsonify(build_response(get_text("kodi_offline", lang), end_session=True))
            
            player_id = get_kodi_active_player()
            item = get_kodi_player_item(player_id) if player_id is not None else None
            
            if not item:
                return jsonify(build_response(get_text("nothing_playing", lang), end_session=True))
            
            media_type = item.get('type')
            title = item.get('title')
            year = item.get('year')
            
            new_url = None
            response_msg = ""

            if media_type == 'movie':
                tmdb_id, r_title, r_year = search_tmdb_movie(title, year=year, lang=lang)
                if tmdb_id:
                    new_url = get_playback_url(tmdb_id, "movie", force_select=True)
                    response_msg = get_text("change_source_movie", lang, r_title)
            
            elif media_type == 'episode':
                show_title = item.get('showtitle')
                season = item.get('season')
                episode = item.get('episode')
                tmdb_id, r_show_name = search_tmdb_show(show_title, lang=lang)
                if tmdb_id:
                    new_url = get_playback_url(tmdb_id, "episode", season, episode, force_select=True)
                    response_msg = get_text("change_source_episode", lang, r_show_name, season, episode)

            if new_url:
                threading.Thread(target=change_source_worker, args=(player_id, new_url)).start()
                return jsonify(build_response(response_msg))
            else:
                return jsonify(build_response(get_text("content_error", lang)))

        elif intent_name == "ResumeTVShowIntent":
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

# ==========================================
# 9. GESTION DE L'ARRÊT DU CONTENEUR
# ==========================================
def handle_sigterm(*args):
    logger.info("Signal SIGTERM reçu d'Unraid/Docker. Fermeture de My Cinema...")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

# --- STARTUP ---
def print_startup_banner():
    conf = get_app_config()
    tmdb = conf.get("TMDB_API_KEY", "")
    masked_key = f"{tmdb[:4]}...{tmdb[-4:]}" if tmdb else "MISSING"
    
    cfg = load_trakt_config()
    masked_trakt = "Loaded" if cfg.get("access_token") else "MISSING"
    skill_sec = "ACTIVE" if conf.get("ALEXA_SKILL_ID") else "DISABLED (WARNING)"

    print("\n" + "="*50)
    print(f" KODI ALEXA CONTROLLER")
    print(f" Version : {APP_VERSION}")
    print(f" Date    : {APP_DATE}")
    print(f" Author  : {APP_AUTHOR}")
    print(f" Debug   : {'ON' if DEBUG_MODE else 'OFF'}")
    print("="*50)
    print(f" [WEB] WebUI Dashboard: Active on Port 5000")
    print(f" [NET] Target OS      : {conf.get('TARGET_OS', 'N/A').upper()}")
    print(f" [NET] Device IP      : {conf.get('SHIELD_IP') or 'MISSING'}")
    print(f" [CFG] Player Auto    : {conf.get('PLAYER_DEFAULT') or 'MISSING'}")
    print(f" [API] TMDB Key       : {masked_key}")
    print(f" [API] Trakt Token    : {masked_trakt}")
    print(f" [SEC] Skill ID Check : {skill_sec}")
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
