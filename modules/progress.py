# modules/progress.py
# Progression de visionnage lue dans le cache Trakt d'un addon Kodi (POV, Fen Light...).
# Depuis le 30/07/2026, Trakt réserve les applications API aux membres VIP : la clé personnelle
# de MyCinema peut être refusée (403). L'addon, lui, reste synchronisé avec Trakt via la clé de
# son auteur ; son cache SQLite donne donc la même information, sans clé API.
import os
import time
import sqlite3
import threading
import requests
from typing import Optional, Tuple, List, Set
from modules.config import logger, get_app_config, DATA_DIR

KODI_ADDON_DATA = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata/addon_data"
DEFAULT_PROGRESS_ADDON = "plugin.video.pov"
LOCAL_DB = os.path.join(DATA_DIR, "kodi_progress_temp.db")
# Intervalle du rafraichissement de fond, quand l'appareil repond.
REFRESH_S = 900

_pull_lock = threading.Lock()
_refresh_started = False

def age_copie() -> Optional[float]:
    """Anciennete de la copie locale en secondes, None si elle n'existe pas."""
    try:
        return time.time() - os.path.getmtime(LOCAL_DB)
    except OSError:
        return None

def _duree(secondes: float) -> str:
    if secondes < 3600: return f"{secondes / 60:.0f} min"
    if secondes < 86400: return f"{secondes / 3600:.1f} h"
    return f"{secondes / 86400:.1f} jours"

def rapatrier(force: bool = False) -> bool:
    """Rapatrie traktcache.db de l'addon par ADB. Vrai si la copie a ete renouvelee.

    Appele par la tache de fond, et en dernier recours quand aucune copie n'existe.
    Jamais sur le chemin d'une demande vocale : Alexa attend quelques secondes, ADB
    peut en prendre autant, et surtout l'appareil est souvent eteint a ce moment-la.
    """
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    if not ip or conf.get("TARGET_OS") != "android":
        return False
    if not _pull_lock.acquire(blocking=force):
        return False  # un rapatriement est deja en cours : ne pas faire la queue
    try:
        from modules.adb import adb_run
        addon = conf.get("PROGRESS_ADDON") or DEFAULT_PROGRESS_ADDON
        remote = f"{KODI_ADDON_DATA}/{addon}/traktcache.db"
        tmp = LOCAL_DB + ".part"
        if os.path.exists(tmp): os.remove(tmp)
        adb_run(ip, lambda d: d.pull(remote, tmp), f"pull {addon}/traktcache.db")
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            return False
        # Une copie tronquee ou illisible empoisonnerait la reprise bien plus
        # surement qu'une copie un peu datee : on ne remplace qu'apres controle.
        try:
            controle = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            controle.execute("SELECT 1 FROM watched_status LIMIT 1").fetchone()
            controle.close()
        except sqlite3.Error as e:
            logger.warning(f"⚠️ [Progression] Copie rapatriee inutilisable ({e}) : l'ancienne est conservee.")
            os.remove(tmp)
            return False
        os.replace(tmp, LOCAL_DB)
        logger.info(f"📥 [Progression] Cache de {addon} rafraichi.")
        return True
    finally:
        _pull_lock.release()

def demarrer_rafraichissement() -> None:
    """Tache de fond qui garde la copie locale a jour quand l'appareil repond.

    C'est elle qui paie le cout d'ADB, hors de toute demande vocale. Le chemin
    vocal se contente alors de lire la copie : instantane, et disponible meme
    appareil eteint.
    """
    global _refresh_started
    if _refresh_started:
        return
    conf = get_app_config()
    if conf.get("TARGET_OS") != "android" or not conf.get("SHIELD_IP"):
        return
    _refresh_started = True

    def boucle() -> None:
        while True:
            try:
                from modules.logic import is_device_online
                if is_device_online(get_app_config().get("SHIELD_IP")):
                    rapatrier(force=True)
            except Exception as e:
                logger.error(f"Erreur du rafraichissement de la progression : {e}")
            time.sleep(REFRESH_S)

    threading.Thread(target=boucle, name="progression-refresh", daemon=True).start()
    logger.info(f"🔄 [Progression] Rafraichissement de fond toutes les {REFRESH_S // 60} min.")

def _aired_episodes(tmdb_id: int) -> List[Tuple[int, int]]:
    """Liste ordonnée (saison, épisode) des épisodes déjà diffusés, hors spéciaux."""
    key = get_app_config().get("TMDB_API_KEY")
    r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", params={"api_key": key}, timeout=5)
    data = r.json()
    last = data.get("last_episode_to_air") or {}
    limit = (last.get("season_number", 0), last.get("episode_number", 0))
    episodes: List[Tuple[int, int]] = []
    for season in sorted(data.get("seasons", []), key=lambda s: s.get("season_number", 0)):
        n = season.get("season_number", 0)
        if n < 1: continue
        for e in range(1, (season.get("episode_count") or 0) + 1):
            if (n, e) <= limit: episodes.append((n, e))
    return episodes

def get_next_episode_from_kodi(tmdb_id: int) -> Tuple[Optional[int], Optional[int], bool]:
    """Renvoie (saison, épisode, source_disponible).

    source_disponible est False quand le cache n'a pas pu être lu : l'appelant peut alors
    tenter une autre source. (None, None, True) signifie : rien à reprendre (jamais commencée ou terminée).
    """
    try:
        age = age_copie()
        if age is None:
            # Aucune copie encore : c'est le seul cas ou l'on accepte de payer ADB
            # ici, faute de quoi une premiere installation ne saurait jamais rien.
            rapatrier(force=True)
            age = age_copie()
            if age is None:
                logger.warning("⚠️ [Progression] Aucune copie du cache de visionnage, et l'appareil est injoignable.")
                return None, None, False
        elif age > 2 * REFRESH_S:
            # On repond quand meme : une copie datee vaut infiniment mieux que
            # le silence, qui serait compris comme "aucune serie en cours".
            logger.info(f"📖 [Progression] Copie du cache vieille de {_duree(age)} : reponse donnee sous reserve.")
        db = sqlite3.connect(f"file:{LOCAL_DB}?mode=ro", uri=True)
        try:
            mid = str(tmdb_id)
            watched: Set[Tuple[int, int]] = set()
            last_seen, last_seen_at = None, ""
            for s, e, played in db.execute("SELECT season, episode, last_played FROM watched_status WHERE db_type='episode' AND media_id=?", (mid,)):
                s, e = int(s), int(e)
                if s < 1: continue
                watched.add((s, e))
                if last_seen is None or (s, e) > last_seen: last_seen, last_seen_at = (s, e), played or ""
            # Un épisode entamé et plus récent que le dernier épisode terminé est prioritaire
            row = db.execute("SELECT season, episode, last_played FROM progress WHERE db_type='episode' AND media_id=? ORDER BY last_played DESC LIMIT 1", (mid,)).fetchone()
        finally:
            db.close()

        if row and (int(row[0]), int(row[1])) not in watched and (row[2] or "") > last_seen_at:
            logger.info(f"📖 [Progression] TMDB {tmdb_id} : épisode entamé S{row[0]}E{row[1]}.")
            return int(row[0]), int(row[1]), True
        if last_seen is None:
            logger.info(f"📖 [Progression] TMDB {tmdb_id} : aucun épisode vu.")
            return None, None, True

        for ep in _aired_episodes(tmdb_id):
            if ep > last_seen:
                logger.info(f"📖 [Progression] TMDB {tmdb_id} : dernier vu S{last_seen[0]}E{last_seen[1]}, suivant S{ep[0]}E{ep[1]}.")
                return ep[0], ep[1], True
        logger.info(f"📖 [Progression] TMDB {tmdb_id} : série terminée (dernier vu S{last_seen[0]}E{last_seen[1]}).")
        return None, None, True
    except Exception as e:
        logger.error(f"Erreur lecture de la progression Kodi pour TMDB {tmdb_id}: {e}")
        return None, None, False
