# scripts/llm_updater.py
import os
import requests
import zipfile
import io
import google.generativeai as genai

# --- Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
APP_PY_PATH = "app.py"

# URLs basées sur ta capture d'écran du repo Fenlight AM
REPO_RAW_BASE = "https://raw.githubusercontent.com/FenlightAnonyMouse/FenlightAnonyMouse.github.io/main/packages"
ADDON_ID = "plugin.video.fenlight"
TARGET_FILE_IN_ZIP = f"{ADDON_ID}/resources/lib/modules/kodi_utils.py"

def main():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY manquante dans l'environnement.")
    
    genai.configure(api_key=GEMINI_API_KEY)

    print(f"Recherche de la dernière version de {ADDON_ID}...")
    
    # 1. Lire le fichier 'fen_light_version' pour obtenir le dernier numéro
    version_url = f"{REPO_RAW_BASE}/fen_light_version"
    r_version = requests.get(version_url)
    if r_version.status_code != 200:
        raise Exception(f"Impossible de lire le fichier de version (Code {r_version.status_code}).")
    
    # On nettoie la chaîne pour enlever les sauts de ligne éventuels
    version = r_version.text.strip()
    print(f"Dernière version trouvée : {version}")

    # 2. Construire l'URL du zip et le télécharger
    zip_url = f"{REPO_RAW_BASE}/{ADDON_ID}-{version}.zip"
    print(f"Téléchargement de l'archive : {zip_url}")
    
    r_zip = requests.get(zip_url)
    if r_zip.status_code != 200:
        raise Exception(f"Impossible de télécharger le zip à l'adresse {zip_url} (Code {r_zip.status_code})")

    # 3. Extraire le fichier cible depuis l'archive en mémoire
    print(f"Extraction de {TARGET_FILE_IN_ZIP}...")
    try:
        with zipfile.ZipFile(io.BytesIO(r_zip.content)) as z:
            with z.open(TARGET_FILE_IN_ZIP) as f:
                kodi_utils_content = f.read().decode('utf-8')
    except KeyError:
        raise Exception(f"Le fichier {TARGET_FILE_IN_ZIP} n'existe pas dans le zip. La structure de l'addon a peut-être changé.")
    except zipfile.BadZipFile:
        raise Exception("Le fichier téléchargé n'est pas une archive zip valide.")

    # 4. Charger l'app.py actuel
    print("Chargement de app.py...")
    with open(APP_PY_PATH, "r", encoding="utf-8") as f:
        app_py_content = f.read()

    # 5. Préparer le prompt pour le LLM
    prompt = f"""
    Tu es un développeur expert en Python.
    Voici le nouveau fichier `kodi_utils.py` d'un addon Kodi (Fen Light), extrait de la version {version} :
    ```python
    {kodi_utils_content}
    ```
    
    Voici mon fichier `app.py` actuel qui contient une logique de "patching" de ce fichier :
    ```python
    {app_py_content}
    ```
    
    Tâche :
    Dans `app.py`, la fonction `check_and_patch_fenlight()` cherche des chaînes de caractères spécifiques (TARGET_1_ORIG, TARGET_2_ORIG, etc.) pour commenter les vérifications de lecture externe.
    Analyse le nouveau `kodi_utils.py` fourni, et vérifie si ces chaînes (ou la logique de blocage externe) ont changé. 
    Mets à jour les variables TARGET_X_ORIG et TARGET_X_PATCH dans mon `app.py` pour qu'elles correspondent au nouveau code de Fen Light afin que la fonction `check_and_patch_fenlight()` continue de fonctionner correctement. 
    Ne modifie RIEN d'autre dans mon `app.py` (garde les numéros de version de mon script, mes routes, etc.).
    
    Réponds UNIQUEMENT avec le code Python complet et mis à jour de `app.py`, sans bloc markdown autour (pas de ```python), prêt à être sauvegardé directement dans le fichier. Ne fais aucun commentaire.
    """

    # 6. Interroger Gemini
    print("Analyse par le LLM Gemini en cours...")
    model = genai.GenerativeModel('gemini-2.5-pro') 
    result = model.generate_content(prompt)
    
    new_app_py = result.text.strip()
    
    # Nettoyage de la réponse (sécurité contre les hallucinations de format)
    if new_app_py.startswith("```python"):
        new_app_py = new_app_py[9:]
    if new_app_py.startswith("```"):
        new_app_py = new_app_py[3:]
    if new_app_py.endswith("```"):
        new_app_py = new_app_py[:-3]
        
    new_app_py = new_app_py.strip()

    # 7. Sauvegarder
    with open(APP_PY_PATH, "w", encoding="utf-8") as f:
        f.write(new_app_py)
    
    print("Mise à jour de app.py terminée avec succès !")

if __name__ == "__main__":
    main()
