# routes/web.py
import os
import paramiko
import requests
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, send_from_directory, current_app
from flask.wrappers import Response
from typing import Union, Tuple
from wakeonlan import send_magic_packet

from modules.config import logger, get_app_config, save_app_config, get_kodi_url
from modules import trakt
from modules.logic import is_device_online, is_device_awake, is_kodi_responsive, search_tmdb_movie, search_tmdb_show, get_next_episode, PROGRESSION_OK, PROGRESSION_INJOIGNABLE, get_tmdb_last_aired, get_playback_url, worker_process
from modules.extensions import executor

web_bp = Blueprint('web', __name__)

@web_bp.before_request
def require_auth():
    if request.endpoint in ['web.health', 'web.serve_icon']:
        return
        
    conf = get_app_config()
    expected_user = conf.get("WEB_UI_USERNAME", "admin")
    expected_pass = conf.get("WEB_UI_PASSWORD", "admin")
    
    if expected_pass:
        auth = request.authorization
        if not auth or auth.username != expected_user or auth.password != expected_pass:
            return Response(
                'Accès non autorisé. Veuillez vous connecter.', 401,
                {'WWW-Authenticate': 'Basic realm="MyCinema Control Panel"'}
            )

@web_bp.route('/')
def dashboard() -> str:
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    # Source annoncée = celle que la chaîne interrogera en premier (cf. get_next_episode)
    if trakt.is_authorized():
        progress_source = 'API TRAKT'
    elif conf.get('TARGET_OS') == 'android' and conf.get('PROGRESS_ADDON'):
        progress_source = conf['PROGRESS_ADDON'].replace('plugin.video.', '').upper() + ' (CACHE TRAKT)'
    else:
        progress_source = ''
    return render_template('dashboard.html', version=current_app.config['APP_VERSION'], device_ok=device_ok,
        device_awake=is_device_awake(conf.get('SHIELD_IP'), conf.get('TARGET_OS')) if device_ok else False,
        kodi_ok=is_kodi_responsive(), shield_ip=conf.get('SHIELD_IP'), target_os=conf.get('TARGET_OS'),
        tmdb_ok=bool(conf.get('TMDB_API_KEY')), progress_source=progress_source,
        p_def=conf.get('PLAYER_DEFAULT'), p_sel=conf.get('PLAYER_SELECT'), skill_id=conf.get('ALEXA_SKILL_ID'))

@web_bp.route('/settings', methods=['GET', 'POST'])
def settings() -> Union[str, Response]:
    if request.method == 'POST':
        action = request.form.get("action")
        if action == "save_config":
            current_config = get_app_config()
            for k in ["TMDB_API_KEY", "ALEXA_SKILL_ID", "TARGET_OS", "SHIELD_IP", "SHIELD_MAC", "KODI_PORT", "KODI_USER", "KODI_PASS", "SSH_USER", "SSH_PASS", "PLAYER_DEFAULT", "PLAYER_SELECT", "PROGRESS_ADDON"]:
                current_config[k] = request.form.get(k, "").strip()
                
            if save_app_config(current_config): 
                logger.info("⚙️ [Config] Configuration système sauvegardée.")
                flash("Config sauvegardée avec succès !", "success")
        return redirect(url_for('web.settings'))
    authorized = trakt.is_authorized()
    trakt_state, trakt_account = trakt.check_authorization() if authorized else ("none", None)
    return render_template('settings.html', version=current_app.config['APP_VERSION'], conf=get_app_config(),
        trakt_configured=trakt.is_configured(), trakt_authorized=authorized,
        trakt_state=trakt_state, trakt_account=trakt_account)

@web_bp.route('/trakt/connect', methods=['POST'])
def trakt_connect() -> Response:
    """Démarre l'autorisation : renvoie le code que l'utilisateur ira saisir chez Trakt."""
    ok, data = trakt.device_code_start()
    return jsonify({"ok": ok, **data})

@web_bp.route('/trakt/poll', methods=['POST'])
def trakt_poll() -> Response:
    """Vérifie si l'utilisateur a validé le code affiché."""
    device_code = (request.json or {}).get("device_code", "")
    if not device_code:
        return jsonify({"state": "invalid", "message": "Code d'appareil manquant."})
    state, message = trakt.device_code_poll(device_code)
    return jsonify({"state": state, "message": message})

@web_bp.route('/trakt/disconnect', methods=['POST'])
def trakt_disconnect() -> Response:
    trakt.disconnect()
    flash("Compte Trakt déconnecté.", "success")
    return redirect(url_for('web.settings'))

@web_bp.route('/health')
def health() -> Tuple[Response, int]: 
    return jsonify({"status": "healthy", "version": current_app.config['APP_VERSION']}), 200

@web_bp.route('/icon.png')
def serve_icon() -> Response: 
    return send_from_directory(os.path.join(os.path.dirname(__file__), '..'), 'icon.png')

@web_bp.route('/web-play', methods=['POST'])
def web_play_route() -> Response:
    query = request.form.get('query')
    media_type = request.form.get('media_type')
    force_select = request.form.get('force_select') == 'on'
    show_action = request.form.get('show_action', 'resume')
    
    if not query:
        flash("Indiquez un titre à rechercher.", "error")
        return redirect(url_for('web.dashboard'))

    if media_type == 'movie':
        logger.info(f"🎬 [Web] Recherche TMDB pour le film : '{query}'...")
        mid, title, _ = search_tmdb_movie(query)
        if mid:
            logger.info(f"🍿 [Web] Lancement du film '{title}' ({'manuel' if force_select else 'auto'})")
            executor.submit(worker_process, get_playback_url(mid, "movie", force_select=force_select))
            flash(f"🎬 Lancement : {title}")
        else:
            flash(f"Aucun film trouvé pour « {query} ». TMDB ne rattrape pas les fautes de frappe : vérifiez l'orthographe.", "error")
    elif media_type == 'show':
        logger.info(f"📺 [Web] Recherche TMDB pour la série : '{query}'...")
        mid, title = search_tmdb_show(query)
        if not mid:
            flash(f"Aucune série trouvée pour « {query} ». TMDB ne rattrape pas les fautes de frappe : vérifiez l'orthographe.", "error")
        else:
            if show_action == 'specific':
                s = request.form.get('season', type=int, default=1)
                e = request.form.get('episode', type=int, default=1)
                logger.info(f"🍿 [Web] Lancement série '{title}' (Saison {s} Épisode {e})")
                executor.submit(worker_process, get_playback_url(mid, "episode", s, e, force_select))
                flash(f"📺 Lancement : {title} S{s}E{e}")
            elif show_action == 'latest':
                ls, le = get_tmdb_last_aired(mid)
                if ls and le:
                    logger.info(f"🍿 [Web] Lancement série '{title}' (Dernier Épisode S{ls}E{le})")
                    executor.submit(worker_process, get_playback_url(mid, "episode", ls, le, force_select))
                    flash(f"📺 Lancement dernier : {title} S{ls}E{le}")
                else:
                    flash(f"TMDB ne connaît pas le dernier épisode diffusé de « {title} ». Rien n'a été lancé.", "error")
            else:
                ts, te, issue = get_next_episode(mid)
                if issue == PROGRESSION_OK:
                    logger.info(f"🍿 [Web] Reprise de '{title}' (Saison {ts} Épisode {te})")
                    executor.submit(worker_process, get_playback_url(mid, "episode", ts, te, force_select))
                    flash(f"📺 Reprise : {title} S{ts}E{te}")
                elif issue == PROGRESSION_INJOIGNABLE:
                    # Surtout ne rien lancer : démarrer S1E1 sans savoir où en est
                    # l'utilisateur est pire que de ne rien faire.
                    logger.warning(f"⚠️ [Web] Progression de '{title}' illisible : aucun lancement.")
                    flash(f"Impossible de savoir où vous en êtes dans « {title} » : aucune source de progression n'a répondu. Rien n'a été lancé.", "error")
                else:
                    logger.info(f"🍿 [Web] '{title}' jamais commencée, lancement S1E1.")
                    executor.submit(worker_process, get_playback_url(mid, "episode", 1, 1, force_select))
                    flash(f"📺 Série jamais commencée. Lancement S1E1 : {title}")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/wake-device', methods=['POST'])
def wake_device_route() -> Response:
    conf = get_app_config()
    mac = conf.get("SHIELD_MAC")
    ip = conf.get("SHIELD_IP")
    logger.info(f"⚡ [Système] Demande de réveil envoyée vers {ip}")
    if mac: 
        try: send_magic_packet(mac)
        except Exception as e: logger.error(f"Erreur WoL signal: {e}")
    if conf.get("TARGET_OS") == "android" and ip:
        from modules.adb import send_adb_command
        send_adb_command(ip, "input keyevent WAKEUP")
    flash("Signal de réveil envoyé.")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/shutdown-device', methods=['POST'])
def shutdown_device_route() -> Response:
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    logger.info(f"💤 [Système] Demande de mise en veille envoyée vers {ip} ({target})")
    if target == "android" and ip:
        from modules.adb import send_adb_command
        res = send_adb_command(ip, "input keyevent SLEEP")
        if res is not None: flash("Commande de mise en veille envoyée (ADB).")
        else: flash("Erreur de communication ADB.")
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
    logger.info(f"▶️ [Système] Lancement de l'application Kodi sur {ip}")
    if conf.get("TARGET_OS") == "android" and ip:
        from modules.adb import send_adb_command
        send_adb_command(ip, "am start -n org.xbmc.kodi/.Splash")
        flash("Start Kodi envoyé (ADB).")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/stop-kodi', methods=['POST'])
def stop_kodi_route() -> Response:
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    logger.info(f"⏹️ [Système] Arrêt de l'application Kodi sur {ip}")
    if is_kodi_responsive():
        try:
            auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
            requests.post(get_kodi_url(conf) or "", json={"jsonrpc": "2.0", "method": "Application.Quit", "id": 1}, auth=auth, timeout=3)
            flash("Kodi arrêté proprement.")
            return redirect(url_for('web.dashboard'))
        except Exception as e: logger.error(f"Erreur Application.Quit: {e}")
    if conf.get("TARGET_OS") == "android" and ip:
        from modules.adb import send_adb_command
        send_adb_command(ip, "am force-stop org.xbmc.kodi")
        flash("Kodi forcé à l'arrêt (ADB).")
    return redirect(url_for('web.dashboard'))

@web_bp.route('/test-connection', methods=['POST'])
def test_connection_route() -> Response:
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    logger.info(f"🔌 [Système] Test de connexion ({target}) vers {ip}...")
    if target == "android" and ip:
        from modules.adb import send_adb_command, ADB_STATE
        res = send_adb_command(ip, "echo ADB_OK")
        if res and "ADB_OK" in res: flash("Test ADB réussi ✅")
        elif ADB_STATE["status"] == "unauthorized": flash("ADB non autorisé 🔐 : acceptez la fenêtre « Autoriser le débogage USB ? » sur la TV (cochez « Toujours autoriser »), puis relancez le test.")
        else: flash("Échec ADB ❌")
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
