# app.py
# VERSION : 2.4.3
# DATE    : 2026-04-14
# DESCRIPTION : Refactoring modulaire - Fichier complet restauré

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_from_directory
import threading
import os
import sys
import subprocess
import paramiko
import time
from datetime import datetime

# Imports locaux
from modules.config import logger, get_app_config, save_app_config, load_trakt_config, load_trakt_token, \
    save_trakt_token_data, refresh_trakt_token_online, get_kodi_url, load_translations, get_text, APP_CONFIG_FILE, LOG_FILE
from modules.logic import is_device_online, is_device_awake, is_kodi_responsive, wake_and_start_kodi, \
    search_tmdb_movie, search_tmdb_show, get_trakt_next_episode, get_playback_url, worker_process, \
    get_tmdb_last_aired, check_episode_exists, get_kodi_active_player, get_kodi_player_item, stop_kodi_playback, change_source_worker
from modules.patcher import PATCH_STATE, check_and_patch_fenlight, patcher_scheduler

# Validation Alexa
from ask_sdk_webservice_support.verifier import RequestVerifier
from wakeonlan import send_magic_packet
import requests

APP_VERSION = "2.4.3"
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")

# ==========================================
# ROUTES FLASK (WEB UI)
# ==========================================

@app.route('/')
def dashboard():
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    return render_template('dashboard.html', version=APP_VERSION, device_ok=device_ok,
        device_awake=is_device_awake(conf.get('SHIELD_IP'), conf.get('TARGET_OS')) if device_ok else False,
        kodi_ok=is_kodi_responsive(), shield_ip=conf.get('SHIELD_IP'), target_os=conf.get('TARGET_OS'),
        tmdb_ok=bool(conf.get('TMDB_API_KEY')), trakt_ok=bool(load_trakt_token()), patch_state=PATCH_STATE,
        p_def=conf.get('PLAYER_DEFAULT'), p_sel=conf.get('PLAYER_SELECT'), skill_id=conf.get('ALEXA_SKILL_ID'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        action = request.form.get("action")
        if action == "save_config":
            new_c = {k: request.form.get(k, "").strip() for k in ["TMDB_API_KEY", "ALEXA_SKILL_ID", "TARGET_OS", "SHIELD_IP", "SHIELD_MAC", "KODI_PORT", "KODI_USER", "KODI_PASS", "SSH_USER", "SSH_PASS", "PLAYER_DEFAULT", "PLAYER_SELECT"]}
            if save_app_config(new_c): flash("Config sauvegardée avec succès !", "success")
        elif action == "save_trakt":
            c_id = request.form.get('client_id')
            c_secret = request.form.get('client_secret')
            pin = request.form.get('pin_code')
            try:
                r = requests.post("https://api.trakt.tv/oauth/token", json={"code": pin, "client_id": c_id, "client_secret": c_secret, "redirect_uri": "urn:ietf:wg:oauth:2.0:oob", "grant_type": "authorization_code"}, headers={'Content-Type': 'application/json'}, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    save_trakt_token_data(data['access_token'], data['refresh_token'], c_id, c_secret)
                    flash("Tokens Trakt générés avec succès !")
                else: flash(f"Erreur Trakt : {r.text}")
            except Exception as e: flash(f"Erreur : {str(e)}")
        return redirect(url_for('settings'))
    return render_template('settings.html', version=APP_VERSION, conf=get_app_config(), trakt_cfg=load_trakt_config())

@app.route('/health')
def health(): return jsonify({"status": "healthy", "version": APP_VERSION}), 200

@app.route('/icon.png')
def serve_icon(): return send_from_directory(os.path.dirname(__file__), 'icon.png')

@app.route('/api/logs', methods=['GET'])
def api_logs():
    try:
        if not os.path.exists(LOG_FILE): return jsonify({"logs": "Aucun log disponible."})
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            return jsonify({"logs": "".join(f.readlines()[-150:])})
    except Exception as e: return jsonify({"logs": f"Erreur : {e}"})

@app.route('/api/status', methods=['GET'])
def api_status():
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    return jsonify({
        "device_ok": device_ok,
        "device_awake": is_device_awake(conf.get('SHIELD_IP'), conf.get('TARGET_OS')) if device_ok else False,
        "kodi_ok": is_kodi_responsive()
    })

# ==========================================
# ROUTES MANUELLES DASHBOARD
# ==========================================

@app.route('/web-play', methods=['POST'])
def web_play_route():
    query = request.form.get('query')
    media_type = request.form.get('media_type')
    force_select = request.form.get('force_select') == 'on'
    show_action = request.form.get('show_action', 'resume')
    
    if media_type == 'movie':
        mid, title, _ = search_tmdb_movie(query)
        if mid:
            threading.Thread(target=worker_process, args=(get_playback_url(mid, "movie", force_select=force_select),)).start()
            flash(f"🎬 Lancement : {title}")
    elif media_type == 'show':
        mid, title = search_tmdb_show(query)
        if mid:
            if show_action == 'specific':
                s, e = request.form.get('season', type=int, default=1), request.form.get('episode', type=int, default=1)
                threading.Thread(target=worker_process, args=(get_playback_url(mid, "episode", s, e, force_select),)).start()
                flash(f"📺 Lancement : {title} S{s}E{e}")
            elif show_action == 'latest':
                s, e = get_tmdb_last_aired(mid)
                if s and e:
                    threading.Thread(target=worker_process, args=(get_playback_url(mid, "episode", s, e, force_select),)).start()
                    flash(f"📺 Lancement dernier : {title} S{s}E{e}")
            else:
                s, e = get_trakt_next_episode(mid)
                if s and e:
                    threading.Thread(target=worker_process, args=(get_playback_url(mid, "episode", s, e, force_select),)).start()
                    flash(f"📺 Reprise : {title} S{s}E{e}")
                else:
                    threading.Thread(target=worker_process, args=(get_playback_url(mid, "episode", 1, 1, force_select),)).start()
                    flash(f"📺 Aucun historique Trakt. Lancement S1E1 : {title}")
    return redirect(url_for('dashboard'))

@app.route('/wake-device', methods=['POST'])
def wake_device_route():
    conf = get_app_config()
    if conf.get("SHIELD_MAC"): 
        try: send_magic_packet(conf.get("SHIELD_MAC"))
        except: pass
    if conf.get("TARGET_OS") == "android" and conf.get("SHIELD_IP"):
        try:
            subprocess.run(["adb", "connect", conf.get("SHIELD_IP")], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        except: pass
    flash("Signal de réveil envoyé.")
    return redirect(url_for('dashboard'))

@app.route('/shutdown-device', methods=['POST'])
def shutdown_device_route():
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if target == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "input", "keyevent", "SLEEP"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Commande de mise en veille envoyée (ADB).")
        except: flash("Erreur ADB.")
    elif target == "libreelec" and ip:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            ssh.exec_command("poweroff")
            ssh.close()
            flash("Extinction envoyée (SSH).")
        except: flash("Erreur SSH.")
    return redirect(url_for('dashboard'))

@app.route('/start-kodi', methods=['POST'])
def start_kodi_route():
    conf = get_app_config()
    if conf.get("TARGET_OS") == "android" and conf.get("SHIELD_IP"):
        try:
            subprocess.run(["adb", "connect", conf.get("SHIELD_IP")], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Start Kodi envoyé (ADB).")
        except: pass
    return redirect(url_for('dashboard'))

@app.route('/stop-kodi', methods=['POST'])
def stop_kodi_route():
    conf = get_app_config()
    if is_kodi_responsive():
        try:
            auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
            requests.post(get_kodi_url(conf), json={"jsonrpc": "2.0", "method": "Application.Quit", "id": 1}, auth=auth, timeout=3)
            flash("Kodi arrêté proprement.")
            return redirect(url_for('dashboard'))
        except: pass
    if conf.get("TARGET_OS") == "android" and conf.get("SHIELD_IP"):
        try:
            subprocess.run(["adb", "connect", conf.get("SHIELD_IP")], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "am", "force-stop", "org.xbmc.kodi"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Kodi forcé à l'arrêt (ADB).")
        except: pass
    return redirect(url_for('dashboard'))

@app.route('/test-connection', methods=['POST'])
def test_connection_route():
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if target == "android":
        try:
            subprocess.run(["adb", "connect", ip], capture_output=True, timeout=5)
            res = subprocess.run(["adb", "shell", "echo", "ADB_OK"], capture_output=True, text=True, timeout=5)
            flash("Test ADB réussi ✅" if "ADB_OK" in res.stdout else "Échec ADB ❌")
        except Exception as e: flash(f"Erreur ADB : {e}")
    elif target == "libreelec":
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            stdin, stdout, stderr = ssh.exec_command("echo SSH_OK")
            flash("Test SSH réussi ✅" if stdout.read().decode('utf-8').strip() == "SSH_OK" else "Échec SSH ❌")
            ssh.close()
        except Exception as e: flash(f"Erreur SSH : {e}")
    return redirect(url_for('dashboard'))

@app.route('/trigger-patch', methods=['POST'])
def trigger_patch_route():
    threading.Thread(target=check_and_patch_fenlight).start()
    flash("Processus de patch lancé.")
    return redirect(url_for('dashboard'))

# ==========================================
# ALEXA WEBHOOK
# ==========================================

@app.route('/alexa-webhook', methods=['POST'])
def alexa_handler():
    raw_body_str = request.get_data(as_text=True)
    try: RequestVerifier().verify({'Signature': request.headers.get('Signature', ''), 'SignatureCertChainUrl': request.headers.get('SignatureCertChainUrl', '')}, raw_body_str, None)
    except Exception: return jsonify({"error": "Forbidden"}), 403

    req_data = request.get_json()
    conf = get_app_config()
    skill_id = conf.get("ALEXA_SKILL_ID")

    if skill_id:
        incoming_id = req_data.get('session', {}).get('application', {}).get('applicationId') or req_data.get('context', {}).get('System', {}).get('application', {}).get('applicationId')
        if incoming_id != skill_id: return jsonify({"error": "Forbidden"}), 403

    req_type = req_data['request']['type']
    lang = req_data['request'].get('locale', 'fr-FR').split('-')[0]
    attributes = req_data.get('session', {}).get('attributes', {})

    if req_type == "LaunchRequest":
        return jsonify(build_res(get_text("launch", lang), end_session=False))

    if req_type == "IntentRequest":
        intent_name = req_data['request']['intent']['name']
        slots = req_data['request']['intent'].get('slots', {})
        force_select = True if slots.get('SourceMode', {}).get('value') else attributes.get('force_select', False)
        manual_msg = get_text("manual_select", lang) if force_select else ""

        if intent_name == "TriggerPatcherIntent":
            threading.Thread(target=check_and_patch_fenlight).start()
            return jsonify(build_res(get_text("patcher_triggered", lang)))

        elif intent_name == "ChangeSourceIntent":
            if not is_kodi_responsive(): return jsonify(build_res(get_text("kodi_offline", lang)))
            pid = get_kodi_active_player()
            item = get_kodi_player_item(pid) if pid is not None else None
            if not item: return jsonify(build_res(get_text("nothing_playing", lang)))
            
            new_url = None
            if item.get('type') == 'movie':
                mid, _, _ = search_tmdb_movie(item.get('title'), year=item.get('year'), lang=lang)
                if mid: new_url = get_playback_url(mid, "movie", force_select=True)
            elif item.get('type') == 'episode':
                mid, _ = search_tmdb_show(item.get('showtitle'), lang=lang)
                if mid: new_url = get_playback_url(mid, "episode", item.get('season'), item.get('episode'), force_select=True)
            
            if new_url:
                threading.Thread(target=change_source_worker, args=(pid, new_url)).start()
                return jsonify(build_res(get_text("change_source_movie" if item.get('type') == 'movie' else "change_source_episode", lang, item.get('title') or item.get('showtitle'), item.get('season'), item.get('episode'))))
            return jsonify(build_res(get_text("content_error", lang)))

        elif intent_name == "ResumeTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            if not query: return jsonify(build_res(get_text("ask_show", lang), False))
            mid, title = search_tmdb_show(query, lang=lang)
            if not mid: return jsonify(build_res(get_text("show_not_found", lang, query)))
            s, e = get_trakt_next_episode(mid)
            if s and e:
                threading.Thread(target=worker_process, args=(get_playback_url(mid, "episode", s, e, force_select),)).start()
                return jsonify(build_res(get_text("resume_show", lang, title, s, e, manual_msg)))
            return jsonify(build_res(get_text("no_progress", lang, title), False))

        elif intent_name == "PlayMovieIntent":
            query = slots.get('MovieName', {}).get('value')
            mid, title, myear = search_tmdb_movie(query, year=slots.get('MovieYear', {}).get('value'), lang=lang)
            if mid:
                threading.Thread(target=worker_process, args=(get_playback_url(mid, "movie", force_select=force_select),)).start()
                return jsonify(build_res(get_text("launch_movie", lang, title, f" de {myear}" if myear else "", manual_msg)))
            return jsonify(build_res(get_text("movie_not_found", lang, query)))

        elif intent_name == "PlayTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            s, e = slots.get('Season', {}).get('value'), slots.get('Episode', {}).get('value')
            mid, title = search_tmdb_show(query, lang=lang) if query else (attributes.get('pending_show_id'), attributes.get('pending_show_name'))
            if not mid: return jsonify(build_res(get_text("show_not_found", lang, query)))
            if s and e:
                if check_episode_exists(mid, s, e):
                    threading.Thread(target=worker_process, args=(get_playback_url(mid, "episode", s, e, force_select),)).start()
                    return jsonify(build_res(get_text("launch_show", lang, title, s, e, manual_msg)))
                return jsonify(build_res(get_text("episode_not_found", lang), False))
            ts, te = get_trakt_next_episode(mid)
            ls, le = get_tmdb_last_aired(mid)
            return jsonify(build_res(get_text("ask_resume", lang, title, ts, te) if ts else get_text("ask_start", lang, title), False, {"pending_show_id": mid, "pending_show_name": title, "step": "ask_playback_method", "force_select": force_select, "trakt_next_s": ts, "trakt_next_e": te, "tmdb_last_s": ls, "tmdb_last_e": le}))

        elif intent_name in ["AMAZON.YesIntent", "ResumeIntent", "ReprendreIntent"]:
            if attributes.get('step') == 'ask_playback_method' and attributes.get('trakt_next_s'):
                s, e = attributes['trakt_next_s'], attributes['trakt_next_e']
                threading.Thread(target=worker_process, args=(get_playback_url(attributes['pending_show_id'], "episode", s, e, force_select),)).start()
                return jsonify(build_res(get_text("resume_show", lang, attributes['pending_show_name'], s, e, get_text("manual_select", lang) if force_select else "")))
            return jsonify(build_res(get_text("nothing_pending", lang)))

        elif intent_name == "LatestEpisodeIntent":
            if attributes.get('step') == 'ask_playback_method':
                s, e = attributes['tmdb_last_s'], attributes['tmdb_last_e']
                threading.Thread(target=worker_process, args=(get_playback_url(attributes['pending_show_id'], "episode", s, e, force_select),)).start()
                return jsonify(build_res(get_text("launch_last", lang, attributes['pending_show_name'])))
            return jsonify(build_res(get_text("unavailable", lang)))

        elif intent_name in ["AMAZON.NoIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"]:
            return jsonify(build_res(get_text("cancelled", lang)))

    return jsonify(build_res(get_text("not_understood", lang)))

def build_res(text, end_session=True, attributes={}):
    return {"version": "1.0", "sessionAttributes": attributes, "response": {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end_session}}

# ==========================================
# INITIALISATION
# ==========================================
if __name__ == '__main__':
    load_translations()
    threading.Thread(target=patcher_scheduler, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
