# routes/api.py
import os
import time
import json
from flask import Blueprint, request, jsonify
from flask.wrappers import Response
from typing import Union, Tuple, Dict, Any, Optional

from modules.config import logger, get_app_config, get_text, LOG_FILE
from modules.logic import is_device_online, is_device_awake, is_kodi_responsive, search_tmdb_movie, search_tmdb_show, get_trakt_next_episode, get_tmdb_last_aired, check_episode_exists, get_playback_url, worker_process, get_kodi_active_player, get_kodi_player_item, change_source_worker
from modules.patcher import check_and_patch_fenlight
from modules.extensions import executor
from ask_sdk_webservice_support.verifier import RequestVerifier

api_bp = Blueprint('api', __name__)

@api_bp.before_request
def require_api_auth():
    # L'endpoint webhook d'Alexa a sa propre authentification par signature
    if request.endpoint == 'api.alexa_handler':
        return
        
    conf = get_app_config()
    expected_user = conf.get("WEB_UI_USERNAME", "admin")
    expected_pass = conf.get("WEB_UI_PASSWORD", "admin")
    
    if expected_pass:
        auth = request.authorization
        if not auth or auth.username != expected_user or auth.password != expected_pass:
            return Response(
                'Accès non autorisé.', 401,
                {'WWW-Authenticate': 'Basic realm="MyCinema API"'}
            )

def build_res(text: str, end_session: bool = True, attributes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if attributes is None: 
        attributes = {}
    return {"version": "1.0", "sessionAttributes": attributes, "response": {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end_session}}

@api_bp.route('/api/logs', methods=['GET'])
def api_logs() -> Response:
    try:
        if not os.path.exists(LOG_FILE): return jsonify({"logs": "Aucun log disponible."})
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            return jsonify({"logs": "".join(f.readlines()[-150:])})
    except Exception as e: 
        logger.error(f"Erreur lecture logs API: {e}")
        return jsonify({"logs": f"Erreur : {e}"})

@api_bp.route('/api/logs/stream', methods=['GET'])
def api_logs_stream():
    def generate():
        if not os.path.exists(LOG_FILE):
            yield f"data: {json.dumps({'logs': 'Aucun log disponible.', 'clear': True})}\n\n"
            while True:
                time.sleep(5)
                yield ": keepalive\n\n"
        
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-150:]
            yield f"data: {json.dumps({'logs': ''.join(lines), 'clear': True})}\n\n"
            while True:
                pos = f.tell()
                line = f.readline()
                if not line:
                    if os.path.getsize(LOG_FILE) < pos:
                        # Si le fichier a été tronqué (effacé), on se replace au début
                        f.seek(0, 0)
                        yield f"data: {json.dumps({'logs': '', 'clear': True})}\n\n"
                    else:
                        time.sleep(0.5)
                    continue
                yield f"data: {json.dumps({'logs': line, 'clear': False})}\n\n"
                
    return Response(generate(), mimetype='text/event-stream')

@api_bp.route('/api/logs/clear', methods=['POST'])
def clear_logs() -> Response:
    try:
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Erreur effacement logs: {e}")
        return jsonify({"error": str(e)}), 500

@api_bp.route('/api/status', methods=['GET'])
def api_status() -> Response:
    conf = get_app_config()
    device_ok = is_device_online(conf.get('SHIELD_IP'))
    return jsonify({
        "device_ok": device_ok,
        "device_awake": is_device_awake(conf.get('SHIELD_IP'), conf.get('TARGET_OS')) if device_ok else False,
        "kodi_ok": is_kodi_responsive()
    })

@api_bp.route('/alexa-webhook', methods=['POST'])
def alexa_handler() -> Union[Tuple[Response, int], Response]:
    raw_body_str = request.get_data(as_text=True)
    try: 
        RequestVerifier().verify({'Signature': request.headers.get('Signature', ''), 'SignatureCertChainUrl': request.headers.get('SignatureCertChainUrl', '')}, raw_body_str, None)
    except Exception as e: 
        logger.warning(f"Signature Alexa invalide ou expirée: {e}")
        return jsonify({"error": "Forbidden"}), 403

    req_data = request.get_json()
    if not req_data:
        return jsonify({"error": "Bad Request"}), 400

    conf = get_app_config()
    skill_id = conf.get("ALEXA_SKILL_ID")

    if skill_id:
        incoming_id = req_data.get('session', {}).get('application', {}).get('applicationId') or req_data.get('context', {}).get('System', {}).get('application', {}).get('applicationId')
        if incoming_id != skill_id: return jsonify({"error": "Forbidden"}), 403

    req_type = req_data['request']['type']
    lang = req_data['request'].get('locale', 'fr-FR').split('-')[0]
    attributes = req_data.get('session', {}).get('attributes', {})

    # Correction pour Amazon Alexa : Ne jamais renvoyer de réponse texte sur SessionEndedRequest
    if req_type == "SessionEndedRequest":
        return jsonify({}), 200

    if req_type == "LaunchRequest":
        return jsonify(build_res(get_text("launch", lang), end_session=False))

    if req_type == "IntentRequest":
        intent_name = req_data['request']['intent']['name']
        slots = req_data['request']['intent'].get('slots', {})
        force_select = True if slots.get('SourceMode', {}).get('value') else attributes.get('force_select', False)
        manual_msg = get_text("manual_select", lang) if force_select else ""

        if intent_name == "TriggerPatcherIntent":
            executor.submit(check_and_patch_fenlight)
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
            
            if new_url and pid is not None:
                executor.submit(change_source_worker, pid, new_url)
                return jsonify(build_res(get_text("change_source_movie" if item.get('type') == 'movie' else "change_source_episode", lang, item.get('title') or item.get('showtitle'), item.get('season'), item.get('episode'))))
            return jsonify(build_res(get_text("content_error", lang)))

        elif intent_name == "ResumeTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            if not query: return jsonify(build_res(get_text("ask_show", lang), False))
            mid, title = search_tmdb_show(query, lang=lang)
            if not mid: return jsonify(build_res(get_text("show_not_found", lang, query)))
            s, e = get_trakt_next_episode(mid)
            if s and e:
                executor.submit(worker_process, get_playback_url(mid, "episode", s, e, force_select))
                return jsonify(build_res(get_text("resume_show", lang, title, s, e, manual_msg)))
            return jsonify(build_res(get_text("no_progress", lang, title), False))

        elif intent_name == "PlayMovieIntent":
            query = slots.get('MovieName', {}).get('value')
            mid, title, myear = search_tmdb_movie(query, year=slots.get('MovieYear', {}).get('value'), lang=lang)
            if mid:
                executor.submit(worker_process, get_playback_url(mid, "movie", force_select=force_select))
                return jsonify(build_res(get_text("launch_movie", lang, title, f" de {myear}" if myear else "", manual_msg)))
            return jsonify(build_res(get_text("movie_not_found", lang, query)))

        elif intent_name == "PlayTVShowIntent":
            query = slots.get('ShowName', {}).get('value')
            s, e = slots.get('Season', {}).get('value'), slots.get('Episode', {}).get('value')
            mid, title = search_tmdb_show(query, lang=lang) if query else (attributes.get('pending_show_id'), attributes.get('pending_show_name'))
            if not mid: return jsonify(build_res(get_text("show_not_found", lang, query)))
            if s and e:
                if check_episode_exists(mid, s, e):
                    executor.submit(worker_process, get_playback_url(mid, "episode", s, e, force_select))
                    return jsonify(build_res(get_text("launch_show", lang, title, s, e, manual_msg)))
                return jsonify(build_res(get_text("episode_not_found", lang), False))
            ts, te = get_trakt_next_episode(mid)
            ls, le = get_tmdb_last_aired(mid)
            return jsonify(build_res(get_text("ask_resume", lang, title, ts, te) if ts else get_text("ask_start", lang, title), False, {"pending_show_id": mid, "pending_show_name": title, "step": "ask_playback_method", "force_select": force_select, "trakt_next_s": ts, "trakt_next_e": te, "tmdb_last_s": ls, "tmdb_last_e": le}))

        elif intent_name in ["AMAZON.YesIntent", "ResumeIntent", "ReprendreIntent"]:
            if attributes.get('step') == 'ask_playback_method' and attributes.get('trakt_next_s'):
                ts, te = attributes['trakt_next_s'], attributes['trakt_next_e']
                executor.submit(worker_process, get_playback_url(attributes['pending_show_id'], "episode", ts, te, force_select))
                return jsonify(build_res(get_text("resume_show", lang, attributes['pending_show_name'], ts, te, get_text("manual_select", lang) if force_select else "")))
            return jsonify(build_res(get_text("nothing_pending", lang)))

        elif intent_name == "LatestEpisodeIntent":
            if attributes.get('step') == 'ask_playback_method':
                ls, le = attributes['tmdb_last_s'], attributes['tmdb_last_e']
                executor.submit(worker_process, get_playback_url(attributes['pending_show_id'], "episode", ls, le, force_select))
                return jsonify(build_res(get_text("launch_last", lang, attributes['pending_show_name'])))
            return jsonify(build_res(get_text("unavailable", lang)))

        elif intent_name in ["AMAZON.NoIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"]:
            return jsonify(build_res(get_text("cancelled", lang)))

    return jsonify(build_res(get_text("not_understood", lang)))
