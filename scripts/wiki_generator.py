import os
import subprocess
import time
import google.generativeai as genai

# --- Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DOCS_DIR = "docs"

# Liste des fichiers à analyser pour donner du contexte au LLM
CONTEXT_FILES = [
    "README.md",
    "app.py",
    "docker-compose.yaml",
    "requirements.txt",
    "translations.json"
]

# Structure du Wiki
WIKI_PAGES = {
    "Home.md": "Présentation générale. Insiste sur l'aspect 'Vibe Coding' et l'architecture Python/Flask/Docker. (FR & EN)",
    "1.-Prerequisites.md": "Liste exhaustive des prérequis basée sur les imports python et le docker-compose. (EN)",
    "2.-Kodi-Setup.md": "Guide technique pour TMDB Helper et les players JSON. (EN)",
    "3.-Docker-Deployment.md": "Documentation détaillée du déploiement. Extrais TOUTES les variables d'environnement trouvées dans app.py et docker-compose.yaml. (EN)",
    "4.-Configuration.md": "Explique le flux d'authentification Trakt et la configuration Alexa (webhook). (EN)",
    "5.-Voice-Commands.md": "Liste des commandes basée sur translations.json et les intents Alexa. (EN)"
}

def setup():
    """Vérifie la clé API et crée le dossier de documentation si nécessaire."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY manquante. Veuillez l'exporter dans votre environnement ou vos secrets.")
    genai.configure(api_key=GEMINI_API_KEY)
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)

def get_full_code_context():
    """Lit les fichiers sources pour créer une base de connaissance pour le LLM."""
    context = "VOICI LE CODE SOURCE DU PROJET POUR CONTEXTE :\n\n"
    for file_path in CONTEXT_FILES:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                context += f"--- FICHIER : {file_path} ---\n"
                context += f.read() + "\n\n"
    return context

def generate_page(model, context, filename, instructions):
    """Demande au LLM de générer une page de wiki spécifique en se basant sur le code source."""
    print(f"🤖 Analyse du code et génération de : {filename}...")
    
    prompt = f"""
    Tu es un expert en documentation technique. 
    Tu as accès au code source complet du projet ci-dessous.
    
    {context}
    
    TACHE :
    Rédige le contenu Markdown de la page "{filename}" en te basant sur le code réel.
    Instructions spécifiques : {instructions}
    
    REGLES :
    - Sois précis techniquement (noms de variables, ports, chemins de fichiers).
    - Ne réponds que par le contenu Markdown brut.
    - Utilise un style professionnel et didactique.
    """
    
    response = model.generate_content(prompt)
    content = response.text.strip()
    
    # Nettoyage des balises markdown si le LLM les a incluses
    for tag in ["```markdown", "```"]:
        if content.startswith(tag): 
            content = content[len(tag):]
        if content.endswith("```"): 
            content = content[:-3]
            
    with open(os.path.join(DOCS_DIR, filename), "w", encoding="utf-8") as f:
        f.write(content.strip())
    print(f"✅ {filename} généré avec succès.")

def git_sync():
    """Ajoute les fichiers générés à Git, commit et push vers le dépôt distant."""
    print("🚀 Synchronisation Git...")
    try:
        subprocess.run(["git", "add", "docs/"], check=True)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", "docs: 🤖 Mise à jour auto du wiki via LLM contextuel"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("🎉 Wiki mis à jour sur GitHub !")
        else:
            print("ℹ️ Aucun changement à synchroniser.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur lors de la synchronisation Git : {e}")

def main():
    print("--- Démarrage de l'Auto-Wiki Generator ---")
    setup()
    context = get_full_code_context()
    
    # Utilisation du modèle flash comme dans votre llm_updater.py existant
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    total_pages = len(WIKI_PAGES)
    for i, (filename, instructions) in enumerate(WIKI_PAGES.items()):
        generate_page(model, context, filename, instructions)
        
        # Ajout d'un délai pour ne pas dépasser la limite de 5 requêtes / minute de l'API gratuite
        if i < total_pages - 1:
            print("⏳ Pause de 15 secondes pour respecter le quota de l'API gratuite...")
            time.sleep(15)
    
    git_sync()

if __name__ == "__main__":
    main()
