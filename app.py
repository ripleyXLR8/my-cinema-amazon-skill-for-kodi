# app.py
# VERSION : 2.4.0
# DATE    : 2026-04-14
# DESCRIPTION : Refactoring modulaire (God Object Fix)

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_from_directory
import threading
import os
import sys
import signal
import requests
from datetime import datetime

# Imports locaux
from modules.config import logger, get_app_config, save_app_config, load_trakt_config, load_trakt_token, \
    save_trakt_token_data, refresh_trakt_token_online, get_kodi_url, load_translations, get_text, APP_CONFIG_FILE
from modules.logic import is_device_online, is_device_awake, is_kodi_responsive, wake_and_start_kodi, \
    search_tmdb_movie, search_tmdb_show, get_trakt_next_episode, get_playback_url, worker_process
from modules.patcher import PATCH_STATE, check_and_patch_fenlight, patcher_scheduler

# Validation Alexa
from ask_sdk_webservice_support.verifier import RequestVerifier

APP_VERSION = "2.4.0"
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")

# --- ROUTES WEB ---
@app.route('/')
def dashboard():
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    return render_template('dashboard.html', version=APP_VERSION, device_ok=device_ok,
        device_awake=is_device_awake(conf.get('SHIELD_IP'), conf.get('TARGET_OS')) if device_ok else False,
        kodi_ok=is_kodi_responsive(), shield_ip=conf.get('SHIELD_IP'), target_os=conf.get('TARGET_OS'),
        tmdb_ok=bool(conf.get('TMDB_API_KEY')), trakt_ok=bool(load_trakt_token()), patch_state=PATCH_STATE)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        action = request.form.get("action")
        if action == "save_config":
            new_c = {k: request.form.get(k, "").strip() for k in ["TMDB_API_KEY", "ALEXA_SKILL_ID", "TARGET_OS", "SHIELD_IP", "SHIELD_MAC", "KODI_PORT", "KODI_USER", "KODI_PASS"]}
            if save_app_config(new_c): flash("Config sauvegardée !")
        return redirect(url_for('settings'))
    return render_template('settings.html', version=APP_VERSION, conf=get_app_config(), trakt_cfg=load_trakt_config())

@app.route('/alexa-webhook', methods=['POST'])
def alexa_handler():
    raw_body = request.get_data(as_text=True)
    try:
        RequestVerifier().verify({'Signature': request.headers.get('Signature'), 'SignatureCertChainUrl': request.headers.get('SignatureCertChainUrl')}, raw_body, None)
    except Exception: return jsonify({"error": "Forbidden"}), 403

    req_data = request.get_json()
    lang = req_data['request'].get('locale', 'fr-FR').split('-')[0]
    intent_name = req_data['request'].get('intent', {}).get('name', '')

    if intent_name == "PlayMovieIntent":
        query = req_data['request']['intent']['slots']['MovieName']['value']
        mid, title, _ = search_tmdb_movie(query, lang=lang)
        if mid:
            threading.Thread(target=worker_process, args=(get_playback_url(mid, "movie"),)).start()
            return jsonify(build_res(get_text("launch_movie", lang, title, "", "")))
    
    return jsonify(build_res(get_text("not_understood", lang)))

def build_res(text):
    return {"version": "1.0", "response": {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": True}}

@app.route('/health')
def health(): return jsonify({"status": "healthy", "version": APP_VERSION}), 200

# --- INITIALISATION ---
if __name__ == '__main__':
    load_translations()
    threading.Thread(target=patcher_scheduler, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
