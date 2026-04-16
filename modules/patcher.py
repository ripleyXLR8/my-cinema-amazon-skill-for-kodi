# modules/patcher.py
import os
import time
import paramiko
from datetime import datetime
from typing import Dict, Any
from modules.config import logger, get_app_config, DATA_DIR

PATCH_STATE: Dict[str, str] = {"status": "Non vérifié", "version": "Inconnue", "last_check": "Jamais"}
FENLIGHT_LOCAL_TEMP: str = os.path.join(DATA_DIR, "kodi_utils_temp.py")

def check_and_patch_fenlight() -> None:
    global PATCH_STATE
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if not ip: return
    
    PATCH_STATE["last_check"] = datetime.now().strftime("%H:%M:%S")
    content: str = ""
    
    try:
        if target == "android":
            from modules.adb import get_adb_device
            device = get_adb_device(ip)
            if not device:
                PATCH_STATE["status"] = "Erreur connexion ADB"
                return
                
            if os.path.exists(FENLIGHT_LOCAL_TEMP): os.remove(FENLIGHT_LOCAL_TEMP)
            # Pull via l'API native Python
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
        logger.error(f"Erreur connexion ou lecture pour le patch ({target}): {e}")
        PATCH_STATE["status"] = "Erreur connexion"
        return

    # Signatures de patch pour le fichier kodi_utils.py (v2.1.98)
    # Les protections pour la lecture externe sont toujours les mêmes
    # au sein des fonctions 'player_check' et 'external_playback_check'.
    # Les chaînes de remplacement actuelles restent efficaces.
    T1_O = "if mode == 'playback.%s' % playback_key():"
    T1_P = "if True: # mode == 'playback.%s' % playback_key():"
    T2_O = "if not playback_key() in params:"
    T2_P = "if False: # not playback_key() in params:"
    
    if T1_P in content and T2_P in content:
        PATCH_STATE["status"] = "Patché"
        return

    if T1_O in content or T2_O in content:
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
        except Exception as e: 
            logger.error(f"Erreur écriture du patch Fen Light ({target}): {e}")
            PATCH_STATE["status"] = "Erreur écriture"

def patcher_scheduler() -> None:
    while True:
        check_and_patch_fenlight()
        time.sleep(3600)