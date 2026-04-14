# modules/patcher.py
import os
import re
import subprocess
import time
import logging
import paramiko
from datetime import datetime
from modules.config import logger, get_app_config, DATA_DIR

PATCH_STATE = {"status": "Non vérifié", "version": "Inconnue", "last_check": "Jamais"}
FENLIGHT_LOCAL_TEMP = os.path.join(DATA_DIR, "kodi_utils_temp.py")

def check_and_patch_fenlight():
    global PATCH_STATE
    conf = get_app_config()
    ip, target = conf.get("SHIELD_IP"), conf.get("TARGET_OS")
    if not ip: return
    
    PATCH_STATE["last_check"] = datetime.now().strftime("%H:%M:%S")
    content = ""
    
    try:
        if target == "android":
            subprocess.run(["adb", "connect", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if os.path.exists(FENLIGHT_LOCAL_TEMP): os.remove(FENLIGHT_LOCAL_TEMP)
            res = subprocess.run(["adb", "pull", "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", FENLIGHT_LOCAL_TEMP], capture_output=True, timeout=10)
            if res.returncode == 0:
                with open(FENLIGHT_LOCAL_TEMP, 'r', encoding='utf-8') as f: content = f.read()
        elif target == "libreelec":
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"), timeout=5)
            with ssh.open_sftp().file("/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", 'r') as f:
                content = f.read().decode('utf-8')
            ssh.close()
    except Exception:
        PATCH_STATE["status"] = "Erreur connexion"
        return

    # Signatures de patch (Cibles pour le script LLM)
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
                subprocess.run(["adb", "push", FENLIGHT_LOCAL_TEMP, "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py"], stdout=subprocess.DEVNULL)
            else:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username=conf.get("SSH_USER"), password=conf.get("SSH_PASS"))
                with ssh.open_sftp().file("/storage/.kodi/addons/plugin.video.fenlight/resources/lib/modules/kodi_utils.py", 'w') as f:
                    f.write(new_content)
                ssh.close()
            PATCH_STATE["status"] = "Patché"
        except Exception: PATCH_STATE["status"] = "Erreur écriture"

def patcher_scheduler():
    while True:
        check_and_patch_fenlight()
        time.sleep(3600)
