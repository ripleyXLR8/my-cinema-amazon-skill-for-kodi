# scripts/llm_updater.py
import os
import requests
import zipfile
import io
import re
import datetime
from google import genai

# --- Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
APP_PY_PATH = "app.py"
PATCHER_PY_PATH = "modules/patcher.py"
CHANGELOG_PATH = "ChangeLog.md"
README_PATH = "README.md"
STATE_FILE_PATH = "scripts/.last_fenlight_version"

REPO_RAW_BASE = "https://raw.githubusercontent.com/FenlightAnonyMouse/FenlightAnonyMouse.github.io/main/packages"
ADDON_ID = "plugin.video.fenlight"
TARGET_FILE_IN_ZIP = f"{ADDON_ID}/resources/lib/modules/kodi_utils.py"

def main():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY manquante dans l'environnement.")
    
    # Initialisation du nouveau client Google GenAI
    client = genai.Client(api_key=GEMINI_API_KEY)

    print(f"Recherche de la dernière version de {ADDON_ID}...")
    version_url = f"{REPO_RAW_BASE}/fen_light_version"
    r_version = requests.get(version_url)
    if r_version.status_code != 200:
        raise Exception(f"Impossible de lire le fichier de version (Code {r_version.status_code}).")
    
    fenlight_version = r_version.text.strip()
    print(f"Dernière version distante trouvée : {fenlight_version}")

    # --- VÉRIFICATION DE L'ÉTAT ---
    if os.path.exists(STATE_FILE_PATH):
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            last_processed_version = f.read().strip()
        
        if last_processed_version == fenlight_version:
            print(f"✅ La version {fenlight_version} de Fen Light a déjà été traitée.")
            print("Aucun patch nécessaire. Fin du script.")
            return
    else:
        print("Aucun historique de version trouvé. Traitement initial en cours...")

    zip_url = f"{REPO_RAW_BASE}/{ADDON_ID}-{fenlight_version}.zip"
    print(f"Téléchargement de l'archive : {zip_url}")
    r_zip = requests.get(zip_url)
    
    print(f"Extraction de {TARGET_FILE_IN_ZIP}...")
    with zipfile.ZipFile(io.BytesIO(r_zip.content)) as z:
        with z.open(TARGET_FILE_IN_ZIP) as f:
            kodi_utils_content = f.read().decode('utf-8')

    print(f"Chargement de {PATCHER_PY_PATH}...")
    with open(PATCHER_PY_PATH, "r", encoding="utf-8") as f:
        patcher_py_content = f.read()

    MD_TICKS = "`" * 3

    # PROMPT : Orienté sur le module patcher.py
    prompt = f"""
    Tu es un développeur expert en Python.
    Voici le nouveau fichier `kodi_utils.py` d'un addon Kodi (Fen Light) (v{fenlight_version}):
    {MD_TICKS}python
    {kodi_utils_content}
    {MD_TICKS}
    
    Voici mon fichier `patcher.py` actuel :
    {MD_TICKS}python
    {patcher_py_content}
    {MD_TICKS}
    
    Tâche :
    Le but de la fonction `check_and_patch_fenlight()` dans mon `patcher.py` est de patcher à la volée le fichier `kodi_utils.py` pour supprimer ou contourner la protection qui empêche la lecture depuis un appel externe (ex: depuis le player TMDB Helper).
    
    1. Analyse le nouveau code de `kodi_utils.py` pour repérer comment l'auteur bloque actuellement les lectures externes (cela tourne souvent autour de `playback_key()`, `external_playback_check`, ou du contrôle du dictionnaire `params`).
    2. Mets à jour la logique interne de la fonction `check_and_patch_fenlight()` dans mon `patcher.py` (variables de signature, chaînes de remplacement, etc.) pour qu'elle désactive efficacement cette sécurité. La méthode habituelle consiste à remplacer les conditions bloquantes par `if True: #` ou `if False: #`.
    3. Tu es libre de modifier complètement la logique de recherche/remplacement au sein de `check_and_patch_fenlight()` si la structure de Fen Light a radicalement changé.
    4. Ne modifie ABSOLUMENT RIEN d'autre dans mon `patcher.py` (imports, reste des fonctions).
    
    Réponds UNIQUEMENT avec le code Python complet et mis à jour de `patcher.py`, sans bloc markdown autour. Ne fais aucun commentaire.
    """

    print("Analyse par le LLM Gemini en cours...")
    
    # Utilisation de la nouvelle méthode du SDK google.genai
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    new_patcher_py = response.text.strip()
    
    # Nettoyage des balises Markdown renvoyées par le LLM
    if new_patcher_py.startswith(MD_TICKS + "python"):
        new_patcher_py = new_patcher_py[9:]
    if new_patcher_py.startswith(MD_TICKS):
        new_patcher_py = new_patcher_py[3:]
    if new_patcher_py.endswith(MD_TICKS):
        new_patcher_py = new_patcher_py[:-3]
        
    new_patcher_py = new_patcher_py.strip()

    # Sauvegarde du nouveau code du patcher
    with open(PATCHER_PY_PATH, "w", encoding="utf-8") as f:
        f.write(new_patcher_py)
    print(f"✅ {PATCHER_PY_PATH} mis à jour avec succès par l'IA.")

    # --- MISE À JOUR DE LA VERSION DANS APP.PY ---
    print("Mise à jour des numéros de version dans app.py...")
    with open(APP_PY_PATH, "r", encoding="utf-8") as f:
        app_py_content = f.read()

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    version_match = re.search(r'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', app_py_content)
    if version_match:
        major, minor, patch = version_match.groups()
        new_version = f"{major}.{minor}.{int(patch) + 1}"
    else:
        new_version = "1.0.0"

    new_app_py = re.sub(r'APP_VERSION\s*=\s*"\d+\.\d+\.\d+"', f'APP_VERSION = "{new_version}"', app_py_content)
    new_app_py = re.sub(r'APP_DATE\s*=\s*"\d{4}-\d{2}-\d{2}"', f'APP_DATE = "{today_str}"', new_app_py)

    with open(APP_PY_PATH, "w", encoding="utf-8") as f:
        f.write(new_app_py)

    # --- MISE À JOUR DU CHANGELOG ET DU README ---
    changelog_entry = f"## [{new_version}] - {today_str}\n- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v{fenlight_version}\n\n"
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            old_changelog = f.read()
        with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write(changelog_entry + old_changelog)
    else:
        with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write("# Changelog\n\n" + changelog_entry)

    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme_content = f.read()
        readme_content = re.sub(r'badge/version-\d+\.\d+\.\d+-', f'badge/version-{new_version}-', readme_content)
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(readme_content)

    print(f"Sauvegarde de l'état (dernière version traitée : {fenlight_version})...")
    with open(STATE_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(fenlight_version)

    print(f"Opération terminée avec succès. Nouvelle version locale : {new_version}")

if __name__ == "__main__":
    main()
