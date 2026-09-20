# modules/adb.py
import os
import time
import threading
from typing import Optional, Dict, Callable, Any
from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.auth.keygen import keygen
from modules.config import logger

ADB_KEY_PATH = "/root/.android/adbkey"

# Durée pendant laquelle la demande d'autorisation reste affichée sur la TV.
# Avec 5 secondes, la fenêtre "Autoriser le débogage USB ?" disparaissait avant qu'on puisse l'accepter.
AUTH_TIMEOUT_S = 120
# Attente maximale d'un appelant (requête web, Alexa) pendant qu'une connexion est en cours
CALLER_WAIT_S = 6
# Délai minimal entre deux tentatives de connexion échouées
RETRY_COOLDOWN_S = 10

# status : unknown | connecting | connected | unauthorized | unreachable
ADB_STATE: Dict[str, str] = {"status": "unknown", "detail": ""}

_device: Optional[AdbDeviceTcp] = None
_device_ip: Optional[str] = None
_cmd_lock = threading.RLock()        # adb_shell n'est pas thread-safe : une commande à la fois
_connect_lock = threading.Lock()
_connect_done = threading.Event()
_connect_done.set()
_last_failure: float = 0.0

def _load_signer() -> PythonRSASigner:
    # Génération automatique des clés RSA si elles n'existent pas
    if not os.path.exists(ADB_KEY_PATH):
        os.makedirs(os.path.dirname(ADB_KEY_PATH), exist_ok=True)
        keygen(ADB_KEY_PATH)
    with open(ADB_KEY_PATH, 'r') as f:
        priv = f.read()
    with open(ADB_KEY_PATH + '.pub', 'r') as f:
        pub = f.read()
    return PythonRSASigner(pub, priv)

def _connect_worker(ip: str) -> None:
    global _device, _device_ip, _last_failure
    needs_approval = {"v": False}

    def on_auth_needed(_dev: Any) -> None:
        needs_approval["v"] = True
        ADB_STATE.update(status="unauthorized", detail="En attente de l'autorisation sur la TV")
        logger.warning(f"🔐 [ADB] {ip} ne reconnaît pas la clé de MyCinema. Acceptez la fenêtre "
                       f"\"Autoriser le débogage USB ?\" sur la TV en cochant \"Toujours autoriser\" "
                       f"(affichée pendant {AUTH_TIMEOUT_S} s).")

    try:
        ADB_STATE.update(status="connecting", detail="")
        device = AdbDeviceTcp(ip, 5555, default_transport_timeout_s=9)
        device.connect(rsa_keys=[_load_signer()], auth_timeout_s=AUTH_TIMEOUT_S, auth_callback=on_auth_needed)
        _device, _device_ip = device, ip
        ADB_STATE.update(status="connected", detail="")
        if needs_approval["v"]:
            logger.info(f"✅ [ADB] Autorisation acceptée sur {ip}.")
    except Exception as e:
        _last_failure = time.time()
        if needs_approval["v"]:
            ADB_STATE.update(status="unauthorized", detail="Autorisation non accordée sur la TV")
            logger.error(f"❌ [ADB] Autorisation non accordée sur {ip} après {AUTH_TIMEOUT_S} s.")
        else:
            ADB_STATE.update(status="unreachable", detail=str(e))
            logger.error(f"Erreur de connexion ADB native à {ip}: {e}")
    finally:
        _connect_done.set()

def _drop_device() -> None:
    global _device
    if _device:
        try: _device.close()
        except Exception: pass
    _device = None

def get_adb_device(ip: str) -> Optional[AdbDeviceTcp]:
    """Renvoie la connexion ADB partagée (pur Python), en l'établissant au besoin.

    La connexion est persistante : ne pas appeler close() dessus. Préférer adb_run().
    """
    if not ip:
        return None
    if _device and _device_ip == ip and _device.available:
        return _device

    with _connect_lock:
        if _connect_done.is_set():
            if _device_ip != ip or (_device and not _device.available):
                _drop_device()
            if time.time() - _last_failure < RETRY_COOLDOWN_S:
                return None
            _connect_done.clear()
            threading.Thread(target=_connect_worker, args=(ip,), daemon=True, name="AdbConnect").start()

    # Une tentative (la nôtre ou celle d'un autre thread) est en cours : on ne patiente que quelques secondes.
    _connect_done.wait(CALLER_WAIT_S)
    if _device and _device_ip == ip and _device.available:
        return _device
    return None

def adb_run(ip: str, action: Callable[[AdbDeviceTcp], Any], label: str = "") -> Any:
    """Exécute action(device) sur la connexion partagée.

    L'action n'est JAMAIS rejouée après un échec : une commande dont la réponse tarde (délai dépassé)
    peut très bien être en cours sur l'appareil, et la relancer l'exécuterait deux fois.
    Seule la connexion est rétablie, pour l'appel suivant.
    """
    device = get_adb_device(ip)
    if not device:
        return None
    with _cmd_lock:
        try:
            return action(device)
        except Exception as e:
            _drop_device()
            logger.error(f"Erreur d'exécution ADB {label} sur {ip}: {e}")
    return None

def send_adb_command(ip: str, command: str) -> Optional[str]:
    """Exécute une commande shell sur le device via ADB."""
    return adb_run(ip, lambda d: d.shell(command), f"'{command}'")
