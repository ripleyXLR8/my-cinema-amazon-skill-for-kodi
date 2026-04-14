# modules/logic.py
import os
import subprocess
import time
import requests
import paramiko
import threading
import logging
from wakeonlan import send_magic_packet
from modules.config import logger, get_app_config, get_kodi_url, load_trakt_token, load_trakt_config, refresh_trakt_token_online

def is_device_online(ip):
    if not ip: return False
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception: return False

def is_device_awake(ip, target_os):
    if not ip or target_os != "android": return True
    try:
        subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        res = subprocess.run(["adb", "shell", "dumpsys", "power"], capture_output=True, text=True, timeout=3)
        return "mWakefulness=Awake" in res.stdout
    except Exception: return False

def is_kodi_responsive():
    url = get_kodi_url(get_app_config())
    if not url: return False
    try:
        r = requests.get(url, timeout=2)
        return r.status_code in [200, 401, 405]
    except Exception: return False

def wake_and_start_kodi():
    conf = get_app_config()
    ip, mac, target = conf.get("SHIELD_IP"), conf.get("SHIELD_MAC"), conf.get("TARGET_OS")
    if not ip: return False
    if is_kodi_responsive(): return True
    if target == "libreelec": return False

    if mac:
        try: send_magic_packet(mac)
        except Exception: pass
    try:
        subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(1)
        subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
    except Exception: pass
    
    for _ in range(30):
        if is_kodi_responsive(): return True
        time.sleep(1)
    return False

def search_tmdb_movie(query, year=None, lang="fr"):
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None, None
    params = {"api_key": tmdb_key, "query": query, "language": "fr-FR" if lang == "fr" else "en-US"}
    if year: params['year'] = year
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=5)
        res = r.json()['results'][0]
        return res['id'], res['title'], res.get('release_date', '')[:4]
    except Exception: return None, None, None

def search_tmdb_show(query, lang="fr"):
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None
    params = {"api_key": tmdb_key, "query": query, "language": "fr-FR" if lang == "fr" else "en-US"}
    try:
        r = requests.get("https://api.themoviedb.org/3/search/tv", params=params, timeout=5)
        res = r.json()['results'][0]
        return res['id'], res['name']
    except Exception: return None, None

def get_trakt_next_episode(tmdb_show_id):
    token = load_trakt_token()
    cfg = load_trakt_config()
    if not cfg.get("client_id") or not token: return None, None
    headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': cfg["client_id"], 'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(f"https://api.trakt.tv/search/tmdb/{tmdb_show_id}?type=show", headers=headers, timeout=5)
        trakt_id = r.json()[0]['show']['ids']['trakt']
        r = requests.get(f"https://api.trakt.tv/shows/{trakt_id}/progress/watched", headers=headers, timeout=5)
        next_ep = r.json().get('next_episode')
        if next_ep: return next_ep['season'], next_ep['number']
    except Exception: pass
    return None, None

def get_playback_url(tmdb_id, media_type, season=None, episode=None, force_select=False):
    conf = get_app_config()
    target_player = conf.get("PLAYER_SELECT") if force_select else conf.get("PLAYER_DEFAULT")
    url = f"plugin://plugin.video.themoviedb.helper/?info=play&player={target_player}"
    if media_type == "movie": return f"{url}&tmdb_id={tmdb_id}&type=movie"
    return f"{url}&tmdb_id={tmdb_id}&season={season}&episode={episode}&type=episode"

def worker_process(plugin_url):
    if not wake_and_start_kodi(): return
    conf = get_app_config()
    url = get_kodi_url(conf)
    if url:
        auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
        try: requests.post(url, json={"jsonrpc": "2.0", "method": "Player.Open", "params": {"item": {"file": plugin_url}}, "id": 1}, auth=auth, timeout=5)
        except Exception: pass
