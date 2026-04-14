# routes/web.py
import os
import subprocess
import paramiko
import requests
import time
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, send_from_directory
from flask.wrappers import Response
from typing import Union, Tuple
from wakeonlan import send_magic_packet

from modules.config import logger, get_app_config, save_app_config, load_trakt_config, load_trakt_token, save_trakt_token_data, get_kodi_url
from modules.logic import is_device_online, is_device_awake, is_kodi_responsive, search_tmdb_movie, search_tmdb_show, get_trakt_next_episode, get_tmdb_last_aired, get_playback_url, worker_process
from modules.patcher import PATCH_STATE, check_and_patch_fenlight
from modules.extensions import executor

web_bp = Blueprint('web', __name__)
APP_VERSION: str = "2.4.9"

@web_bp.route('/')
def dashboard() -> str:
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    return render_template('dashboard.html', version=APP_VERSION, device_ok=device_ok,
        device_awake=is_device_awake(conf.get('SHIELD_IP'), conf.get('TARGET_OS')) if device_ok else False,
        kodi_ok=is_kodi_responsive(), shield_ip=conf.get('SHIELD_IP'), target_os=conf.get('TARGET_OS'),
        tmdb_ok=bool(conf.get('TMDB_API_KEY')), trakt_ok=bool(load_trakt_token()), patch_state=PATCH_STATE,
        p_def=conf.get('PLAYER_DEFAULT'), p_sel=conf.get('PLAYER_SELECT'), skill_id=conf.get('ALEXA_SKILL_ID'))

@web_bp.route('/settings', methods=['GET', 'POST'])
def settings() -> Union[str, Response]:
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
                else: 
                    logger.error(f"Erreur réponse Trakt OAuth: {r.text}")
                    flash(f"Erreur Trakt : {r.text}")
            except Exception as e: 
                logger.error(f"Exception lors de l'auth Trakt: {e}")
                flash(f"Erreur : {str(e)}")
        return redirect(url_for('web.settings'))
    return render_template('settings.html', version=APP_VERSION, conf=get_app_config(), trakt_cfg=load_trakt_config())

@web_bp.route('/health')
def health() -> Tuple[Response, int]: 
    return jsonify({"status": "healthy", "version": APP_VERSION}), 200

@web_bp.route('/icon.png')
def serve_icon() -> Response: 
    return send_from_directory(os.path.join(os.path.dirname(__file__), '..'), 'icon.png')

@web_bp.route('/web-play', methods=['POST'])
def web_play_route() -> Response:
    query = request.form.get('query')
    media_type = request.form.get('media_type')
    force_select = request.form.get('force_select') == 'on'
    show_action = request.form.get('show_action', 'resume')
    
    if media_type == 'movie' and query:
        mid, title, _ = search_tmdb_movie(query)
        if mid:
            executor.submit(worker_process, get_playback_url(mid, "movie", force_select=force_select))
            flash(f"🎬 Lancement : {title}")
    elif media_type == 'show' and query:
        mid, title = search_tmdb_show(query)
        if mid:
            if show_action == 'specific':
                s = request.form.get('season', type=int, default=1)
                e = request.form.get('episode', type=int, default=1)
                executor.submit(worker_process, get_playback_url(mid, "episode", s, e, force_select))
                flash(f"📺 Lancement : {title} S{s}E{e}")
            elif show_action == 'latest':
                ls, le = get_tmdb_last_aired(mid)
                if ls and le:
                    executor.submit(worker_process, get_playback_url(mid, "episode", ls, le, force_select))
                    flash(f"📺 Lancement dernier : {title} S{ls}E{le}")
            else:
                ts, te = get_trakt_next_episode(mid)
                if ts and te:
                    executor.submit(worker_process, get_playback_url(mid, "episode", ts, te, force_select))
                    flash(f"📺 Reprise : {title} S{ts}E{te}")
                else:
                    executor.submit(worker_process, get_playback_url(mid, "episode", 1, 1, force_select))
                    flash(f"📺 Aucun historique Trakt. Lancement S1E1 : {title}")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/wake-device', methods=['POST'])
def wake_device_route() -> Response:
    conf = get_app_config()
    mac = conf.get("SHIELD_MAC")
    ip = conf.get("SHIELD_IP")
    if mac: 
        try: send_magic_packet(mac)
        except Exception as e: logger.error(f"Erreur WoL signal: {e}")
    if conf.get("TARGET_OS") == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        except Exception as e: logger.error(f"Erreur ADB wakeup: {e}")
    flash("Signal de réveil envoyé.")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/shutdown-device', methods=['POST'])
def shutdown_device_route() -> Response:
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if target == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "input", "keyevent", "SLEEP"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Commande de mise en veille envoyée (ADB).")
        except Exception as e: 
            logger.error(f"Erreur ADB sleep: {e}")
            flash("Erreur ADB.")
    elif target == "libreelec" and ip:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            ssh.exec_command("poweroff")
            ssh.close()
            flash("Extinction envoyée (SSH).")
        except Exception as e: 
            logger.error(f"Erreur SSH poweroff: {e}")
            flash("Erreur SSH.")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/start-kodi', methods=['POST'])
def start_kodi_route() -> Response:
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    if conf.get("TARGET_OS") == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Start Kodi envoyé (ADB).")
        except Exception as e: logger.error(f"Erreur ADB start kodi: {e}")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/stop-kodi', methods=['POST'])
def stop_kodi_route() -> Response:
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    if is_kodi_responsive():
        try:
            auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
            requests.post(get_kodi_url(conf) or "", json={"jsonrpc": "2.0", "method": "Application.Quit", "id": 1}, auth=auth, timeout=3)
            flash("Kodi arrêté proprement.")
            return redirect(url_for('web.dashboard'))
        except Exception as e: logger.error(f"Erreur Application.Quit: {e}")
    if conf.get("TARGET_OS") == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
            subprocess.run(["adb", "shell", "am", "force-stop", "org.xbmc.kodi"], stdout=subprocess.DEVNULL, timeout=5)
            flash("Kodi forcé à l'arrêt (ADB).")
        except Exception as e: logger.error(f"Erreur ADB force-stop: {e}")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/test-connection', methods=['POST'])
def test_connection_route() -> Response:
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if target == "android" and ip:
        try:
            subprocess.run(["adb", "connect", ip], capture_output=True, timeout=5)
            res = subprocess.run(["adb", "shell", "echo", "ADB_OK"], capture_output=True, text=True, timeout=5)
            flash("Test ADB réussi ✅" if "ADB_OK" in res.stdout else "Échec ADB ❌")
        except Exception as e: 
            logger.error(f"Erreur test ADB: {e}")
            flash(f"Erreur ADB : {e}")
    elif target == "libreelec" and ip:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            stdin, stdout, stderr = ssh.exec_command("echo SSH_OK")
            flash("Test SSH réussi ✅" if stdout.read().decode('utf-8').strip() == "SSH_OK" else "Échec SSH ❌")
            ssh.close()
        except Exception as e: 
            logger.error(f"Erreur test SSH: {e}")
            flash(f"Erreur SSH : {e}")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/trigger-patch', methods=['POST'])
def trigger_patch_route() -> Response:
    executor.submit(check_and_patch_fenlight)
    flash("Processus de patch lancé.")
    return redirect(url_for('web.dashboard'))
