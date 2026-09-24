# modules/logic.py
import os
import subprocess
import time
import requests
import paramiko
import logging
from typing import Optional, Tuple, Dict, Any
from wakeonlan import send_magic_packet
from modules.config import logger, get_app_config, get_kodi_url
from modules.adb import send_adb_command

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
        res = send_adb_command(ip, "dumpsys power")
        return res is not None and "mWakefulness=Awake" in res
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

    logger.info(f"🔄 [Kodi] Kodi injoignable, tentative de réveil de l'appareil...")
    if mac:
        try:
            send_magic_packet(mac)
        except Exception as e:
            logger.error(f"Erreur Wake-on-LAN ({mac}): {e}")
    try:
        send_adb_command(ip, "input keyevent WAKEUP")
        time.sleep(1)
        send_adb_command(ip, "am start -n org.xbmc.kodi/.Splash")
    except Exception as e:
        logger.error(f"Erreur lors du réveil ADB vers {ip}: {e}")
    
    for _ in range(30):
        if is_kodi_responsive(): 
            logger.info("✅ [Kodi] Appareil réveillé et Kodi prêt !")
            return True
        time.sleep(1)
    
    logger.error("❌ [Kodi] Impossible de démarrer Kodi après 30 secondes.")
    return False

def search_tmdb_movie(query: str, year: Optional[str] = None, lang: str = "fr") -> Tuple[Optional[int], Optional[str], Optional[str]]:
    conf = get_app_config()
    tmdb_key = conf.get("TMDB_API_KEY")
    if not tmdb_key: return None, None, None
    params: Dict[str, Any] = {"api_key": tmdb_key, "query": query, "language": "fr-FR" if lang == "fr" else "en-US"}
    if year: params['year'] = year
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=5)
        # Zero resultat n'est pas une anomalie : c'est une reponse. La traiter en
        # exception faisait apparaitre un "list index out of range" dans les
        # journaux, qui donne a lire un bug la ou il n'y a qu'une faute de frappe.
        resultats = r.json().get('results') or []
        if not resultats:
            logger.info(f"🔎 [TMDB] Aucun film ne correspond à '{query}'.")
            return None, None, None
        res = resultats[0]
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
        resultats = r.json().get('results') or []
        if not resultats:
            logger.info(f"🔎 [TMDB] Aucune série ne correspond à '{query}'.")
            return None, None
        res = resultats[0]
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

# Issues possibles d'une recherche de progression. La distinction compte : dire
# « pas de progression » quand on n'a simplement pas pu lire la progression est
# un mensonge, et il envoie l'utilisateur chercher une panne du mauvais côté.
PROGRESSION_OK = 'ok'                    # un épisode à reprendre
PROGRESSION_RIEN = 'rien'                # source consultée : rien à reprendre
PROGRESSION_INJOIGNABLE = 'injoignable'  # aucune source n'a pu répondre

def get_next_episode(tmdb_show_id: int) -> Tuple[Optional[int], Optional[int], str]:
    """Épisode à reprendre, demandé aux sources de progression dans l'ordre.

    L'ordre n'est pas arbitraire : Trakt vient en premier parce que c'est la seule
    source qui répond quand l'appareil Kodi est éteint — et c'est précisément le
    moment où l'on demande à Alexa de reprendre une série. Le cache de l'addon
    prend le relais pour qui n'a pas connecté de compte Trakt.

    Chaque source renvoie un drapeau « source disponible » : on ne passe à la
    suivante que si la précédente n'a pas pu répondre. Une source qui répond
    « rien à reprendre » fait donc autorité, elle n'est pas contredite par une
    source moins fiable.

    Renvoie (saison, épisode, issue) où issue vaut PROGRESSION_OK, _RIEN ou
    _INJOIGNABLE. L'appelant doit distinguer les deux derniers : « rien à
    reprendre » est une réponse, « injoignable » est un aveu d'ignorance.
    """
    from modules.progress import get_next_episode_from_kodi
    from modules.trakt import get_next_episode as get_next_episode_from_trakt

    for source in (get_next_episode_from_trakt, get_next_episode_from_kodi):
        s, e, source_ok = source(tmdb_show_id)
        if source_ok:
            return (s, e, PROGRESSION_OK) if s and e else (None, None, PROGRESSION_RIEN)
    logger.warning(f"⚠️ [Progression] Aucune source n'a pu répondre pour TMDB {tmdb_show_id}.")
    return None, None, PROGRESSION_INJOIGNABLE

def get_playback_url(tmdb_id: int, media_type: str, season: Optional[int] = None, episode: Optional[int] = None, force_select: bool = False) -> str:
    conf = get_app_config()
    target_player = conf.get("PLAYER_SELECT") if force_select else conf.get("PLAYER_DEFAULT")
    url = f"plugin://plugin.video.themoviedb.helper/?info=play&player={target_player}"
    if media_type == "movie": return f"{url}&tmdb_id={tmdb_id}&type=movie"
    return f"{url}&tmdb_id={tmdb_id}&season={season}&episode={episode}&type=episode"

def resoudre_lecture(tmdb_id: int, media_type: str, season: Optional[int] = None,
                     episode: Optional[int] = None, force_select: bool = False,
                     titre: str = '', addonid: Optional[str] = None) -> Tuple[str, str]:
    """(url, verbe JSON-RPC) pour lancer ce contenu.

    Voie directe si elle est configurée ET qu'une recette existe pour l'addon
    visé ; TMDb Helper dans tous les autres cas. Le repli est silencieux et sans
    condition : une configuration directe incomplète ne doit jamais empêcher une
    lecture qui marchait avant.
    """
    from modules import lecteurs
    if lecteurs.mode_direct():
        cible = addonid or lecteurs.lecteur_par_defaut()
        if cible:
            resultat = lecteurs.construire_url(cible, media_type, tmdb_id, titre,
                                               season, episode, force_select)
            if resultat:
                logger.info(f"🎬 [Lecture] Contrôle direct de {lecteurs.nom_lecteur(cible)}.")
                return resultat
            logger.warning(f"⚠️ [Lecture] Pas de recette pour {cible}, repli sur TMDb Helper.")
    return get_playback_url(tmdb_id, media_type, season, episode, force_select), 'play'

def worker_process(plugin_url: str, verbe: str = 'play') -> None:
    """Envoie l'ordre à Kodi. Le verbe depend de ce que rend l'addon vise.

    Player.Open sert a LIRE, GUI.ActivateWindow a NAVIGUER. Demander a Kodi de
    lire un dossier echoue en silence et le ramene a l'accueil : c'est le cas
    des addons qui presentent d'abord une liste de resultats.
    """
    if not wake_and_start_kodi(): return
    conf = get_app_config()
    url = get_kodi_url(conf)
    if not url: return
    auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
    if verbe == 'activate':
        methode = "GUI.ActivateWindow"
        params = {"window": "videos", "parameters": [plugin_url]}
    else:
        methode = "Player.Open"
        params = {"item": {"file": plugin_url}}
    logger.info(f"▶️ [Lecture] Envoi de la requête JSON-RPC vers Kodi ({methode})")
    try:
        requests.post(url, json={"jsonrpc": "2.0", "method": methode, "params": params, "id": 1}, auth=auth, timeout=5)
        logger.info("✅ [Lecture] Ordre pris en compte par Kodi.")
    except Exception as e:
        logger.error(f"❌ [Lecture] Erreur exécution requête Kodi {methode}: {e}")

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
        logger.info(f"⏹️ [Lecture] Lecture arrêtée (Player {player_id})")
    except Exception as e:
        logger.error(f"Erreur arrêt lecture Kodi: {e}")

def change_source_worker(player_id: int, next_url: str) -> None:
    logger.info("🔄 [Lecture] Changement de source demandé, arrêt de la lecture en cours...")
    stop_kodi_playback(player_id)
    time.sleep(2)
    worker_process(next_url)
