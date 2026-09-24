# modules/trakt.py
# Progression de visionnage lue directement chez Trakt.
#
# C'est la seule source qui répond quand l'appareil Kodi est éteint : elle
# interroge les serveurs de Trakt, pas la machine du salon. L'autorisation se
# fait par « code d'appareil » — l'utilisateur lit huit caractères à l'écran et
# les saisit sur trakt.tv/activate — donc sans application à créer ni jeton à
# recopier à la main.
import time
import threading
import requests
from typing import Optional, Tuple, Dict, Any
from modules.config import (logger, load_trakt_config, save_trakt_token_data,
                            get_valid_trakt_token)

API = "https://api.trakt.tv"
TIMEOUT_S = 8

# Correspondance id TMDB -> id Trakt. Elle ne change jamais pour une série
# donnée : la garder en mémoire épargne un aller-retour réseau à chaque
# demande vocale, là où chaque centaine de millisecondes compte.
_show_ids: Dict[int, int] = {}
_ids_lock = threading.Lock()


def _headers(with_auth: bool = True) -> Optional[Dict[str, str]]:
    cfg = load_trakt_config()
    client_id = cfg.get("client_id")
    if not client_id: return None
    h = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": client_id}
    if with_auth:
        token = get_valid_trakt_token()
        if not token: return None
        h["Authorization"] = f"Bearer {token}"
    return h


def is_configured() -> bool:
    """Des identifiants d'application sont disponibles (embarqués ou fournis)."""
    return bool(load_trakt_config().get("client_id"))


def is_authorized() -> bool:
    """Un compte utilisateur a autorisé l'application."""
    return bool(load_trakt_config().get("access_token"))


# --- Autorisation par code d'appareil -------------------------------------

def device_code_start() -> Tuple[bool, Dict[str, Any]]:
    """Demande un code à afficher. Ne concède aucun accès : tant que personne ne
    saisit le code sur trakt.tv/activate, rien n'est autorisé."""
    cfg = load_trakt_config()
    if not cfg.get("client_id"):
        return False, {"error": "Aucun identifiant d'application Trakt n'est configuré."}
    try:
        r = requests.post(f"{API}/oauth/device/code", json={"client_id": cfg["client_id"]}, timeout=TIMEOUT_S)
        if r.status_code == 200:
            d = r.json()
            logger.info("🔑 [Trakt] Code d'appareil demandé, en attente de la saisie de l'utilisateur.")
            return True, {"user_code": d.get("user_code"), "verification_url": d.get("verification_url"),
                          "device_code": d.get("device_code"), "interval": d.get("interval", 5),
                          "expires_in": d.get("expires_in", 600)}
        logger.error(f"❌ [Trakt] Demande de code refusée (HTTP {r.status_code}).")
        return False, {"error": f"Trakt a refusé la demande (HTTP {r.status_code})."}
    except Exception as e:
        logger.error(f"❌ [Trakt] Erreur à la demande de code : {e}")
        return False, {"error": str(e)}


# Réponses du flux par code d'appareil, telles que Trakt les documente.
_POLL_MESSAGES = {
    400: ("pending", "En attente de votre validation sur trakt.tv/activate."),
    404: ("invalid", "Code inconnu : relancez la connexion."),
    409: ("used", "Ce code a déjà servi."),
    410: ("expired", "Code expiré : relancez la connexion."),
    418: ("denied", "Autorisation refusée sur Trakt."),
    429: ("slow_down", "Trakt demande de ralentir les vérifications."),
}


def device_code_poll(device_code: str) -> Tuple[str, str]:
    """Vérifie si l'utilisateur a validé le code. Renvoie (état, message).

    état vaut 'ok' une fois les jetons enregistrés, 'pending' tant que l'utilisateur
    n'a pas validé, et l'une des erreurs ci-dessus sinon.
    """
    cfg = load_trakt_config()
    if not (cfg.get("client_id") and cfg.get("client_secret")):
        return "invalid", "Identifiants d'application Trakt incomplets (client_secret manquant)."
    try:
        r = requests.post(f"{API}/oauth/device/token", json={
            "code": device_code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"]
        }, timeout=TIMEOUT_S)
        if r.status_code == 200:
            d = r.json()
            save_trakt_token_data(d["access_token"], d["refresh_token"],
                                  cfg["client_id"], cfg["client_secret"], d.get("expires_in"))
            logger.info("✅ [Trakt] Compte autorisé, jetons enregistrés.")
            return "ok", "Compte Trakt connecté."
        state, message = _POLL_MESSAGES.get(r.status_code, ("error", f"Réponse inattendue de Trakt (HTTP {r.status_code})."))
        if state not in ("pending", "slow_down"):
            logger.error(f"❌ [Trakt] Autorisation interrompue : {message}")
        return state, message
    except Exception as e:
        logger.error(f"❌ [Trakt] Erreur pendant l'autorisation : {e}")
        return "error", str(e)


def disconnect() -> bool:
    """Oublie l'autorisation de l'utilisateur et repart des identifiants fournis.

    Les identifiants d'application enregistrés ne sont volontairement PAS réécrits :
    le fichier de jetons est fusionné par-dessus les variables d'environnement, si
    bien qu'un client_id périmé (une application supprimée chez Trakt, par exemple)
    masquerait celui embarqué dans l'image — y compris pendant une tentative de
    reconnexion, qui échouerait alors sans recours. En les laissant tomber, on
    revient à TRAKT_CLIENT_ID / TRAKT_CLIENT_SECRET ou aux identifiants embarqués.
    """
    cfg = load_trakt_config()
    token = cfg.get("access_token")
    if token and cfg.get("client_id") and cfg.get("client_secret"):
        try:
            requests.post(f"{API}/oauth/revoke", json={
                "token": token, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"]
            }, timeout=TIMEOUT_S)
        except Exception as e:
            logger.warning(f"⚠️ [Trakt] Révocation côté Trakt impossible ({e}) ; autorisation oubliée localement.")
    ok = save_trakt_token_data("", "")
    logger.info("🔌 [Trakt] Compte déconnecté.")
    return ok


# --- Lecture de la progression --------------------------------------------

def _trakt_show_id(tmdb_id: int, headers: Dict[str, str]) -> Optional[int]:
    with _ids_lock:
        if tmdb_id in _show_ids: return _show_ids[tmdb_id]
    r = requests.get(f"{API}/search/tmdb/{tmdb_id}", params={"type": "show"}, headers=headers, timeout=TIMEOUT_S)
    if r.status_code != 200: return None
    results = r.json()
    if not results: return None
    show_id = results[0].get("show", {}).get("ids", {}).get("trakt")
    if show_id:
        with _ids_lock:
            _show_ids[tmdb_id] = show_id
    return show_id


def get_next_episode(tmdb_id: int) -> Tuple[Optional[int], Optional[int], bool]:
    """Renvoie (saison, épisode, source_disponible), même contrat que le cache de l'addon.

    source_disponible est False quand Trakt n'a pas pu être interrogé : l'appelant
    passe alors à la source suivante. (None, None, True) signifie que Trakt a
    répondu et qu'il n'y a rien à reprendre — série jamais commencée, ou terminée.
    """
    headers = _headers()
    if not headers: return None, None, False
    try:
        show_id = _trakt_show_id(tmdb_id, headers)
        if not show_id:
            logger.warning(f"⚠️ [Trakt] Série TMDB {tmdb_id} introuvable chez Trakt.")
            return None, None, False
        r = requests.get(f"{API}/shows/{show_id}/progress/watched", headers=headers, timeout=TIMEOUT_S)
        if r.status_code in (401, 403):
            logger.error(f"❌ [Trakt] Accès refusé (HTTP {r.status_code}) : l'autorisation du compte est à refaire.")
            return None, None, False
        if r.status_code != 200:
            logger.error(f"❌ [Trakt] Progression indisponible (HTTP {r.status_code}).")
            return None, None, False
        data = r.json()
        nxt = data.get("next_episode")
        if not nxt:
            logger.info(f"📖 [Trakt] TMDB {tmdb_id} : rien à reprendre ({data.get('completed', 0)}/{data.get('aired', 0)} vus).")
            return None, None, True
        logger.info(f"📖 [Trakt] TMDB {tmdb_id} : {data.get('completed', 0)}/{data.get('aired', 0)} vus, suivant S{nxt['season']}E{nxt['number']}.")
        return int(nxt["season"]), int(nxt["number"]), True
    except Exception as e:
        logger.error(f"❌ [Trakt] Erreur de lecture de la progression pour TMDB {tmdb_id} : {e}")
        return None, None, False


def check_authorization() -> Tuple[str, Optional[str]]:
    """Vérifie que l'autorisation enregistrée est encore acceptée par Trakt.

    Renvoie ('ok', nom du compte), ('invalid', None) si Trakt la refuse — jeton
    révoqué, ou application supprimée —, ('unknown', None) si la vérification
    elle-même a échoué (réseau), et ('absente', None) si aucune autorisation
    n'est enregistrée.

    Ces quatre cas sont volontairement distincts. Confondre « refusée » et
    « rien d'enregistré » ferait annoncer un rejet de Trakt à quelqu'un qui ne
    s'est jamais connecté ; confondre « refusée » et « injoignable » ferait
    annoncer une autorisation à refaire à quelqu'un dont la connexion a
    simplement hoqueté.
    """
    cfg = load_trakt_config()
    if not cfg.get("access_token"):
        return "absente", None
    headers = _headers()
    if not headers:
        # Un jeton existe, mais plus d'identifiants d'application : on ne peut
        # rien vérifier, donc on n'affirme rien.
        return "unknown", None
    try:
        r = requests.get(f"{API}/users/settings", headers=headers, timeout=TIMEOUT_S)
        if r.status_code == 200:
            return "ok", r.json().get("user", {}).get("username")
        if r.status_code in (401, 403):
            logger.warning(f"⚠️ [Trakt] L'autorisation enregistrée est refusée (HTTP {r.status_code}) : elle est à refaire.")
            return "invalid", None
        return "unknown", None
    except Exception as e:
        logger.warning(f"⚠️ [Trakt] Vérification de l'autorisation impossible : {e}")
        return "unknown", None
