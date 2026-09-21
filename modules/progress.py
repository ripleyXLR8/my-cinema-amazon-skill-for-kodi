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
PULL_TTL_S = 30

_pull_lock = threading.Lock()
_last_pull: float = 0.0

def _pull_progress_db() -> bool:
    """Rapatrie traktcache.db de l'addon par ADB (au plus une fois toutes les PULL_TTL_S secondes)."""
    global _last_pull
    conf = get_app_config()
    ip = conf.get("SHIELD_IP")
    if not ip or conf.get("TARGET_OS") != "android":
        return False
    with _pull_lock:
        if time.time() - _last_pull < PULL_TTL_S and os.path.exists(LOCAL_DB):
            return True
        from modules.adb import adb_run
        addon = conf.get("PROGRESS_ADDON") or DEFAULT_PROGRESS_ADDON
        remote = f"{KODI_ADDON_DATA}/{addon}/traktcache.db"
        tmp = LOCAL_DB + ".part"
        if os.path.exists(tmp): os.remove(tmp)
        adb_run(ip, lambda d: d.pull(remote, tmp), f"pull {addon}/traktcache.db")
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            logger.warning(f"⚠️ [Progression] Cache de visionnage introuvable sur l'appareil ({remote}).")
            return False
        os.replace(tmp, LOCAL_DB)
        _last_pull = time.time()
        return True

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
        if not _pull_progress_db():
            return None, None, False
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
