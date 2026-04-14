# modules/logic.py
import os
import subprocess
import time
import requests
import paramiko
import threading
import logging
from typing import Optional, Tuple, Dict, Any
from wakeonlan import send_magic_packet
from modules.config import logger, get_app_config, get_kodi_url, load_trakt_token, load_trakt_config, refresh_trakt_token_online

def is_device_online(ip: Optional[str]) -> bool:
    if not ip: return False
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception as e:
        logger.error(f"Erreur ping device {ip}: {e}")
        return False

def is_device_awake(ip: Optional[str], target_os: str) -> bool:
    if not ip or target_os != "android": return True
    try:
        subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        res = subprocess.run(["adb", "shell", "dumpsys", "power"], capture_output=True, text=True, timeout=3)
        return "mWakefulness=Awake" in res.stdout
    except Exception as e:
        logger.error(f"Erreur vérification éveil {ip}: {e}")
        return False

def is_kodi_responsive() -> bool:
    url = get_kodi_url(get_app_config())
    if not url: return False
    try:
        r = requests.get(url, timeout=2)
        return r.status_code in [200, 401, 405]
    except requests.exceptions.ConnectionError:
        logger.debug(f"Kodi non joignable (Connection refused). En attente d'allumage...")
        return False
    except Exception as e:
        logger.error(f"Erreur inattendue vérification Kodi: {e}")
        return False

def wake_and_start_kodi() -> bool:
    conf = get_app_config()
    ip, mac, target = conf.get("SHIELD_IP"), conf.get("SHIELD_MAC"), conf.get("TARGET_OS")
    if not ip: return False
    if is_kodi_responsive(): return True
    if target == "libreelec": return False

    if mac:
        try:
            send_magic_packet(mac)
        except Exception as e:
            logger.error(f"Erreur Wake-on-LAN ({mac}): {e}")
    try:
        subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, timeout=5)
        subprocess.run(["adb", "shell", "input", "keyevent", "WAKEUP"], stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(1)
        subprocess.run(["adb", "shell", "am", "start", "-n", "org.xbmc.kodi/.Splash"], stdout=subprocess.DEVNULL, timeout=5)
    except Exception as e:
        logger.error(f"Erreur ADB wake_and_start vers {ip}: {e}")
    
    for _ in range(30):
        if is_kodi_responsive(): return True
        time.sleep(1)
    return False

def search_tmdb_movie(query: str, year: Optional[str] = None, lang: str = "fr") -> Tuple[Optional[int], Optional[str], Optional[str]]:
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None, None
    params: Dict[str, Any] = {"api_key": tmdb_key, "query": query, "language": "fr-FR" if lang == "fr" else "en-US"}
    if year: params['year'] = year
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=5)
        res = r.json()['results'][0]
        return res['id'], res['title'], res.get('release_date', '')[:4]
    except Exception as e:
        logger.error(f"Erreur recherche film TMDB '{query}': {e}")
        return None, None, None

def search_tmdb_show(query: str, lang: str = "fr") -> Tuple[Optional[int], Optional[str]]:
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None
    params = {"api_key": tmdb_key, "query": query, "language": "fr-FR" if lang == "fr" else "en-US"}
    try:
        r = requests.get("https://api.themoviedb.org/3/search/tv", params=params, timeout=5)
        res = r.json()['results'][0]
        return res['id'], res['name']
    except Exception as e:
        logger.error(f"Erreur recherche série TMDB '{query}': {e}")
        return None, None

def check_episode_exists(tmdb_id: int, season: int, episode: int) -> bool:
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return False
    try:
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}", params={"api_key": tmdb_key}, timeout=2)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Erreur vérification épisode TMDB {tmdb_id} S{season}E{episode}: {e}")
        return True

def get_tmdb_last_aired(tmdb_id: int) -> Tuple[Optional[int], Optional[int]]:
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None
    try:
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", params={"api_key": tmdb_key}, timeout=2)
        last_ep = r.json().get('last_episode_to_air')
        if last_ep: return last_ep['season_number'], last_ep['episode_number']
    except Exception as e:
        logger.error(f"Erreur récupération dernier épisode TMDB {tmdb_id}: {e}")
    return None, None

def get_trakt_next_episode(tmdb_show_id: int) -> Tuple[Optional[int], Optional[int]]:
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
    except Exception as e:
        logger.error(f"Erreur récupération prochain épisode Trakt pour TMDB {tmdb_show_id}: {e}")
    return None, None

def get_playback_url(tmdb_id: int, media_type: str, season: Optional[int] = None, episode: Optional[int] = None, force_select: bool = False) -> str:
    conf = get_app_config()
    target_player = conf.get("PLAYER_SELECT") if force_select else conf.get("PLAYER_DEFAULT")
    url = f"plugin://plugin.video.themoviedb.helper/?info=play&player={target_player}"
    if media_type == "movie": return f"{url}&tmdb_id={tmdb_id}&type=movie"
    return f"{url}&tmdb_id={tmdb_id}&season={season}&episode={episode}&type=episode"

def worker_process(plugin_url: str) -> None:
    if not wake_and_start_kodi(): return
    conf = get_app_config()
    url = get_kodi_url(conf)
    if url:
        auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
        try: 
            requests.post(url, json={"jsonrpc": "2.0", "method": "Player.Open", "params": {"item": {"file": plugin_url}}, "id": 1}, auth=auth, timeout=5)
        except Exception as e:
            logger.error(f"Erreur exécution requête Kodi Player.Open: {e}")

def get_kodi_active_player() -> Optional[int]:
    conf = get_app_config()
    url = get_kodi_url(conf)
    if not url: return None
    try:
        auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
        r = requests.post(url, json={"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1}, auth=auth, timeout=3)
        for player in r.json().get('result', []):
            if player.get('type') == 'video': return player.get('playerid')
    except Exception as e:
        logger.error(f"Erreur récupération lecteurs actifs Kodi: {e}")
    return None

def get_kodi_player_item(player_id: int) -> Optional[Dict[str, Any]]:
    conf = get_app_config()
    url = get_kodi_url(conf)
    if not url: return None
    try:
        auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
        payload = {"jsonrpc": "2.0", "method": "Player.GetItem", "params": {"properties": ["title", "year", "season", "episode", "showtitle"], "playerid": player_id}, "id": 1}
        r = requests.post(url, json=payload, auth=auth, timeout=3)
        return r.json().get('result', {}).get('item')
    except Exception as e:
        logger.error(f"Erreur récupération item lecteur Kodi {player_id}: {e}")
    return None

def stop_kodi_playback(player_id: int) -> None:
    conf = get_app_config()
    url = get_kodi_url(conf)
    if not url: return
    try:
        auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
        requests.post(url, json={"jsonrpc": "2.0", "method": "Player.Stop", "params": {"playerid": player_id}, "id": 1}, auth=auth, timeout=3)
    except Exception as e:
        logger.error(f"Erreur arrêt lecture Kodi: {e}")

def change_source_worker(player_id: int, next_url: str) -> None:
    stop_kodi_playback(player_id)
    time.sleep(2)
    worker_process(next_url)
