# modules/adb.py
import os
from typing import Optional
from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.auth.keygen import keygen
from modules.config import logger

ADB_KEY_PATH = "/root/.android/adbkey"

def get_adb_device(ip: str) -> Optional[AdbDeviceTcp]:
    """Établit une connexion ADB native en pur Python."""
    if not ip: 
        return None
    
    try:
        # Génération automatique des clés RSA si elles n'existent pas
        if not os.path.exists(ADB_KEY_PATH):
            os.makedirs(os.path.dirname(ADB_KEY_PATH), exist_ok=True)
            keygen(ADB_KEY_PATH)
        
        with open(ADB_KEY_PATH, 'r') as f:
            priv = f.read()
        with open(ADB_KEY_PATH + '.pub', 'r') as f:
            pub = f.read()
        
        signer = PythonRSASigner(pub, priv)
        
        # Initialisation de la connexion avec timeout
        device = AdbDeviceTcp(ip, 5555, default_transport_timeout_s=5)
        device.connect(rsa_keys=[signer], auth_timeout_s=5)
        return device
    except Exception as e:
        logger.error(f"Erreur de connexion ADB native à {ip}: {e}")
        return None

def send_adb_command(ip: str, command: str) -> Optional[str]:
    """Exécute une commande shell sur le device via ADB."""
    device = get_adb_device(ip)
    if device:
        try:
            res = device.shell(command)
            device.close()
            return res
        except Exception as e:
            logger.error(f"Erreur d'exécution de la commande ADB '{command}' sur {ip}: {e}")
    return None
