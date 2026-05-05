# modules/patcher.py
import os
import time
import paramiko
import requests
from datetime import datetime
from typing import Dict, Any
from modules.config import logger, get_app_config, DATA_DIR, get_kodi_url

PATCH_STATE: Dict[str, str] = {"status": "Non vérifié", "version": "Inconnue", "last_check": "Jamais"}
FENLIGHT_LOCAL_TEMP: str = os.path.join(DATA_DIR, "kodi_utils_temp.py")
LAST_VERSION_FILE: str = os.path.join(os.path.dirname(__file__), "..", "scripts", ".last_fenlight_version")

def check_and_patch_fenlight() -> None:
    global PATCH_STATE
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if not ip: return
    
    PATCH_STATE["last_check"] = datetime.now().strftime("%H:%M:%S")
    logger.info(f"🔎 [Patcher] Vérification de l'état de Fen Light sur l'appareil ({ip})...")

    # 1. Fallback: Lecture du dernier fichier de version connu
    if os.path.exists(LAST_VERSION_FILE):
        try:
            with open(LAST_VERSION_FILE, 'r', encoding='utf-8') as f:
                PATCH_STATE["version"] = f.read().strip()
        except Exception:
            pass

    # 2. Précision: Interrogation de Kodi en direct s'il est allumé
    try:
        url = get_kodi_url(conf)
        if url:
            auth = (conf.get("KODI_USER"), conf.get("KODI_PASS")) if conf.get("KODI_USER") else None
            payload = {
                "jsonrpc": "2.0", 
                "method": "Addons.GetAddonDetails", 
                "params": {"addonid": "plugin.video.fenlight", "properties": ["version"]}, 
                "id": 1
            }
            r = requests.post(url, json=payload, auth=auth, timeout=2)
            if r.status_code == 200:
                ver = r.json().get('result', {}).get('addon', {}).get('version')
                if ver:
                    PATCH_STATE["version"] = ver
    except Exception:
        pass 

    content: str = ""
    
    try:
        if target == "android":
            from modules.adb import get_adb_device
            device = get_adb_device(ip)
            if not device:
                PATCH_STATE["status"] = "Erreur connexion ADB"
                logger.error("❌ [Patcher] Impossible de se connecter via ADB pour vérifier le patch.")
                return
                
            if os.path.exists(FENLIGHT_LOCAL_TEMP): os.remove(FENLIGHT_LOCAL_TEMP)
            device.pull("/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", FENLIGHT_LOCAL_TEMP)
            device.close()
            
            if os.path.exists(FENLIGHT_LOCAL_TEMP):
                with open(FENLIGHT_LOCAL_TEMP, 'r', encoding='utf-8') as f: content = f.read()
            else:
                raise Exception("Pull ADB échoué.")
                
        elif target == "libreelec":
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            with ssh.open_sftp().file("/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", 'r') as f:
                content = f.read().decode('utf-8')
            ssh.close()
    except Exception as e:
        logger.error(f"❌ [Patcher] Erreur de lecture pour le patch ({target}): {e}")
        PATCH_STATE["status"] = "Erreur connexion"
        return

    # Signatures de patch pour le fichier kodi_utils.py (Fen Light v2.2.04)
    # Les protections pour la lecture externe sont toujours situées aux mêmes emplacements.
    # Elles sont dans les fonctions 'player_check' et 'external_playback_check'.
    T1_O = "if mode == 'playback.%s' % playback_key():"
    T1_P = "if True: # mode == 'playback.%s' % playback_key():"
    T2_O = "if not playback_key() in params:"
    T2_P = "if False: # not playback_key() in params:"
    
    if T1_P in content and T2_P in content:
        PATCH_STATE["status"] = "Patché"
        logger.info(f"✅ [Patcher] Fen Light v{PATCH_STATE['version']} est déjà parfaitement patché.")
        return

    if T1_O in content or T2_O in content:
        logger.info(f"⚠️ [Patcher] Sécurités détectées sur Fen Light v{PATCH_STATE['version']}. Application du patch en cours...")
        new_content = content.replace(T1_O, T1_P).replace(T2_O, T2_P)
        try:
            if target == "android":
                with open(FENLIGHT_LOCAL_TEMP, 'w', encoding='utf-8') as f: f.write(new_content)
                from modules.adb import get_adb_device
                device = get_adb_device(ip)
                if device:
                    device.push(FENLIGHT_LOCAL_TEMP, "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py")
                    device.close()
                else:
                    raise Exception("Impossible de se reconnecter pour le push ADB.")
            else:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"))
                with ssh.open_sftp().file("/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", 'w') as f:
                    f.write(new_content)
                ssh.close()
            PATCH_STATE["status"] = "Patché"
            logger.info("🚀 [Patcher] Patch appliqué avec succès ! La lecture externe est maintenant autorisée.")
        except Exception as e: 
            logger.error(f"❌ [Patcher] Erreur lors de l'écriture du patch ({target}): {e}")
            PATCH_STATE["status"] = "Erreur écriture"

def patcher_scheduler() -> None:
    while True:
        check_and_patch_fenlight()
        time.sleep(3600)