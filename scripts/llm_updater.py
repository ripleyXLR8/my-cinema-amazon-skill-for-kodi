# scripts/llm_updater.py
import os
import requests
import zipfile
import io
import re
import datetime
import google.generativeai as genai

# --- Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
APP_PY_PATH = "app.py"
CHANGELOG_PATH = "ChangeLog.md"
README_PATH = "README.md"

REPO_RAW_BASE = "https://raw.githubusercontent.com/FenlightAnonyMouse/FenlightAnonyMouse.github.io/main/packages"
ADDON_ID = "plugin.video.fenlight"
TARGET_FILE_IN_ZIP = f"{ADDON_ID}/resources/lib/modules/kodi_utils.py"

def main():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY manquante dans l'environnement.")
    
    genai.configure(api_key=GEMINI_API_KEY)

    print(f"Recherche de la dernière version de {ADDON_ID}...")
    version_url = f"{REPO_RAW_BASE}/fen_light_version"
    r_version = requests.get(version_url)
    if r_version.status_code != 200:
        raise Exception(f"Impossible de lire le fichier de version (Code {r_version.status_code}).")
    
    fenlight_version = r_version.text.strip()
    print(f"Dernière version trouvée : {fenlight_version}")

    zip_url = f"{REPO_RAW_BASE}/{ADDON_ID}-{fenlight_version}.zip"
    print(f"Téléchargement de l'archive : {zip_url}")
    r_zip = requests.get(zip_url)
    
    print(f"Extraction de {TARGET_FILE_IN_ZIP}...")
    with zipfile.ZipFile(io.BytesIO(r_zip.content)) as z:
        with z.open(TARGET_FILE_IN_ZIP) as f:
            kodi_utils_content = f.read().decode('utf-8')

    print("Chargement de app.py...")
    with open(APP_PY_PATH, "r", encoding="utf-8") as f:
        app_py_content = f.read()

    # Utilisation d'une variable pour éviter les bugs de rendu markdown de l'interface
    MD_TICKS = "`" * 3

    prompt = f"""
    Tu es un développeur expert en Python.
    Voici le nouveau fichier `kodi_utils.py` d'un addon Kodi (Fen Light) (v{fenlight_version}):
    {MD_TICKS}python
    {kodi_utils_content}
    {MD_TICKS}
    
    Voici mon fichier `app.py` actuel :
    {MD_TICKS}python
    {app_py_content}
    {MD_TICKS}
    
    Tâche :
    Analyse le nouveau `kodi_utils.py` et mets à jour les variables TARGET_X_ORIG et TARGET_X_PATCH dans mon `app.py` pour qu'elles correspondent au nouveau code. 
    Ne modifie RIEN d'autre dans mon `app.py` (ne touche pas aux versions, aux imports ou au reste de la logique).
    Réponds UNIQUEMENT avec le code Python complet, sans bloc markdown autour. Ne fais aucun commentaire.
    """

    print("Analyse par le LLM Gemini en cours...")
    model = genai.GenerativeModel('gemini-2.5-flash') 
    result = model.generate_content(prompt)
    
    new_app_py = result.text.strip()
    
    # Nettoyage sécurisé
    if new_app_py.startswith(MD_TICKS + "python"):
        new_app_py = new_app_py[9:]
    if new_app_py.startswith(MD_TICKS):
        new_app_py = new_app_py[3:]
    if new_app_py.endswith(MD_TICKS):
        new_app_py = new_app_py[:-3]
        
    new_app_py = new_app_py.strip()

    # --- AUTO INCREMENT VERSION ---
    print("Mise à jour des numéros de version...")
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # Extraire l'ancienne version
    version_match = re.search(r'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', app_py_content)
    if version_match:
        major, minor, patch = version_match.groups()
        new_version = f"{major}.{minor}.{int(patch) + 1}" # +0.0.1
    else:
        new_version = "1.0.0"

    # Remplacer dans app.py
    new_app_py = re.sub(r'APP_VERSION\s*=\s*"\d+\.\d+\.\d+"', f'APP_VERSION = "{new_version}"', new_app_py)
    new_app_py = re.sub(r'APP_DATE\s*=\s*"\d{4}-\d{2}-\d{2}"', f'APP_DATE = "{today_str}"', new_app_py)

    with open(APP_PY_PATH, "w", encoding="utf-8") as f:
        f.write(new_app_py)

    # --- MISE A JOUR CHANGELOG ---
    changelog_entry = f"## [{new_version}] - {today_str}\n- 🤖 Vibe Coding : Mise à jour automatique des signatures pour Fen Light version {fenlight_version}\n\n"
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            old_changelog = f.read()
        with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write(changelog_entry + old_changelog)
    else:
        with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write("# Changelog\n\n" + changelog_entry)

    # --- MISE A JOUR README ---
    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme_content = f.read()
        
        # Met à jour le badge version dans le readme
        readme_content = re.sub(r'badge/version-\d+\.\d+\.\d+-', f'badge/version-{new_version}-', readme_content)
        
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(readme_content)

    print(f"Opération terminée avec succès. Nouvelle version : {new_version}")

if __name__ == "__main__":
    main()
