# modules/lecteurs.py
# Contrôle direct des addons Kodi, en alternative à TMDb Helper.
#
# TMDb Helper reste la voie par défaut : c'est la couche d'abstraction qui rend
# MyCinema compatible avec n'importe quel lecteur, sans rien connaître de sa
# grammaire d'URL. On ne la remplace pas — on ajoute une voie directe pour les
# cas qu'elle ne sait pas traiter (vStream fait tomber Kodi à travers elle, par
# conflit de dialogues de progression) ou quand on veut éviter son détour.
#
# Savoir qu'un addon est installé ne dit rien sur la façon de le piloter : il
# faut une recette par addon. C'est le prix de la voie directe, et la raison
# pour laquelle on ne propose que les addons dont la recette est vérifiée.
import re
import unicodedata
from typing import Dict, List, Optional, Tuple, Any
from modules.config import logger, get_app_config

# Verbes JSON-RPC : tous les addons ne se pilotent pas de la même façon.
#   'play'     -> Player.Open        : l'addon résout une lecture
#   'activate' -> GUI.ActivateWindow : l'addon renvoie une liste à parcourir
VERBE_LECTURE = 'play'
VERBE_NAVIGATION = 'activate'

# Recettes vérifiées en conditions réelles. Chaque gabarit n'emploie que des
# valeurs dont MyCinema dispose déjà.
RECETTES: Dict[str, Dict[str, Any]] = {
    'plugin.video.pov': {
        'nom': 'POV',
        'verbe': VERBE_LECTURE,
        'episode_exact': True,   # sait viser une saison et un épisode précis
        'film': ('plugin://plugin.video.pov/?mode=play_media'
                 '&tmdb_id={tmdb_id}&autoplay={autoplay}'),
        'episode': ('plugin://plugin.video.pov/?mode=play_media'
                    '&tmdb_id={tmdb_id}&mediatype=episode'
                    '&season={season}&episode={episode}&autoplay={autoplay}'),
    },
    'plugin.video.vstream': {
        'nom': 'vStream',
        'verbe': VERBE_NAVIGATION,
        'episode_exact': False,  # sa recherche ne prend qu'un titre
        # Le titre FRANÇAIS est indispensable : « Band of Brothers » ramène
        # « L'Enfer du Pacifique », une autre série. MyCinema interroge TMDB
        # en fr-FR, il a donc déjà le bon titre.
        'film': ('plugin://plugin.video.vstream/?site=globalSearch'
                 '&function=searchGlobal&searchtext={titre}&sCat=1'),
        'episode': ('plugin://plugin.video.vstream/?site=globalSearch'
                    '&function=searchGlobal&searchtext={titre}&sCat=2'),
    },
}


def mode_direct() -> bool:
    return get_app_config().get('CONTROL_MODE', 'tmdb_helper') == 'direct'


def addons_installes() -> List[Dict[str, str]]:
    """Addons vidéo installés et activés, vus par Kodi lui-même.

    On interroge Kodi en JSON-RPC plutôt que de lire son dossier par ADB :
    ça marche sur toutes les plateformes, y compris LibreELEC qui n'a pas d'ADB,
    et ça ne voit que les addons réellement activés.
    """
    import requests
    from modules.config import get_kodi_url
    conf = get_app_config()
    url = get_kodi_url(conf)
    if not url:
        return []
    auth = (conf.get('KODI_USER'), conf.get('KODI_PASS')) if conf.get('KODI_USER') else None
    try:
        r = requests.post(url, json={'jsonrpc': '2.0', 'method': 'Addons.GetAddons', 'id': 1,
                                     'params': {'type': 'xbmc.python.pluginsource', 'content': 'video',
                                                'enabled': True, 'properties': ['name', 'version']}},
                          auth=auth, timeout=8)
        addons = r.json().get('result', {}).get('addons', [])
    except Exception as e:
        logger.error(f"❌ [Lecteurs] Liste des addons impossible : {e}")
        return []
    return [{'addonid': a['addonid'], 'nom': a.get('name', a['addonid']),
             'version': a.get('version', '')} for a in addons]


def addons_pilotables() -> List[Dict[str, str]]:
    """Intersection entre ce qui est installé et ce qu'on sait piloter.

    N'afficher que cette intersection évite de proposer une case à cocher qui
    ne mènerait à rien : une recette manquante n'est pas rattrapable côté
    utilisateur.
    """
    connus = []
    for a in addons_installes():
        if a['addonid'] in RECETTES:
            a = dict(a)
            a['episode_exact'] = RECETTES[a['addonid']]['episode_exact']
            connus.append(a)
    return connus


def lecteurs_configures() -> List[Dict[str, str]]:
    """Addons activés en contrôle direct, avec leur mot-clé vocal.

    Format stocké : "addonid:mot-clé|addonid:mot-clé". Un mot-clé vide désigne
    le lecteur employé quand la phrase n'en contient aucun.
    """
    brut = (get_app_config().get('DIRECT_PLAYERS') or '').strip()
    lecteurs = []
    for entree in brut.split('|'):
        entree = entree.strip()
        if not entree:
            continue
        addonid, _, motcle = entree.partition(':')
        addonid = addonid.strip()
        if addonid in RECETTES:
            lecteurs.append({'addonid': addonid, 'motcle': motcle.strip()})
        else:
            logger.warning(f"⚠️ [Lecteurs] '{addonid}' n'a pas de recette connue, ignoré.")
    return lecteurs


def _sans_accents(texte: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', texte)
                   if unicodedata.category(c) != 'Mn').lower()


def extraire_motcle(requete: str) -> Tuple[str, Optional[str]]:
    """Sépare le mot-clé du titre prononcé.

    Renvoie (titre nettoyé, addonid choisi ou None). Les slots Alexa étant des
    slots personnalisés attrape-tout, le mot-clé arrive DANS le titre : « lance
    L'Homme Bicentenaire en français ». On l'extrait ici plutôt que d'ajouter un
    slot, ce qui éviterait de republier le modèle d'interaction de la skill.
    """
    if not requete:
        return requete, None
    nettoye = _sans_accents(requete)
    meilleur = None
    for lecteur in lecteurs_configures():
        motcle = lecteur['motcle']
        if not motcle:
            continue
        cible = _sans_accents(motcle)
        # En fin de phrase de préférence : c'est là qu'on le prononce.
        motif = re.compile(r'\s*\b' + re.escape(cible) + r'\b\s*$')
        m = motif.search(nettoye)
        if not m:
            motif = re.compile(r'\s*\b' + re.escape(cible) + r'\b\s*')
            m = motif.search(nettoye)
        if not m:
            continue
        # Le mot-clé le plus long l'emporte : « en francais » avant « francais ».
        if meilleur is None or len(cible) > len(meilleur[0]):
            meilleur = (cible, lecteur['addonid'], m.span())
    if not meilleur:
        return requete, None
    debut, fin = meilleur[2]
    titre = (requete[:debut] + ' ' + requete[fin:]).strip()
    titre = re.sub(r'\s+', ' ', titre)
    mot = requete[debut:fin].strip()
    # Le mot-clé est retiré du titre dans tous les cas : « en français » n'aide
    # pas une recherche TMDB. Mais il ne route que si le mode direct est actif —
    # annoncer un routage qui sera ignoré revient à mentir dans le journal.
    if not mode_direct():
        logger.warning(
            f"⚠️ [Lecteurs] Mot-clé '{mot}' reconnu, mais le contrôle direct est "
            f"désactivé : il est retiré du titre et le routage vers "
            f"{nom_lecteur(meilleur[1])} est ignoré (TMDb Helper reste la voie).")
        return titre, None
    logger.info(f"🎯 [Lecteurs] Mot-clé reconnu : '{mot}' -> {meilleur[1]}")
    return titre, meilleur[1]


def lecteur_par_defaut() -> Optional[str]:
    """Addon à employer quand aucun mot-clé n'a été prononcé."""
    lecteurs = lecteurs_configures()
    sans_motcle = [l['addonid'] for l in lecteurs if not l['motcle']]
    if sans_motcle:
        return sans_motcle[0]
    return lecteurs[0]['addonid'] if lecteurs else None


def construire_url(addonid: str, media_type: str, tmdb_id: int, titre: str = '',
                   season: Any = None, episode: Any = None,
                   force_select: bool = False) -> Optional[Tuple[str, str]]:
    """(url, verbe JSON-RPC) pour cet addon, ou None si la recette manque."""
    recette = RECETTES.get(addonid)
    if not recette:
        return None
    gabarit = recette['film'] if media_type == 'movie' else recette['episode']
    try:
        from urllib.parse import quote
        url = gabarit.format(
            tmdb_id=tmdb_id,
            titre=quote(titre or ''),
            season=season if season is not None else '',
            episode=episode if episode is not None else '',
            autoplay='false' if force_select else 'true',
        )
    except KeyError as e:
        logger.error(f"❌ [Lecteurs] Gabarit de {addonid} incomplet : {e}")
        return None
    return url, recette['verbe']


def episode_exact(addonid: str) -> bool:
    """Cet addon sait-il viser un épisode précis ?

    vStream ne le sait pas : sa recherche ne prend qu'un titre. Le dire permet
    d'annoncer honnêtement « j'ouvre la série » au lieu de laisser croire à une
    reprise à l'épisode près.
    """
    return bool(RECETTES.get(addonid, {}).get('episode_exact'))


def nom_lecteur(addonid: str) -> str:
    return RECETTES.get(addonid, {}).get('nom', addonid)
