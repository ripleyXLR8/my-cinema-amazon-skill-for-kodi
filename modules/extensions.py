# modules/extensions.py
from concurrent.futures import ThreadPoolExecutor

# Initialisation de l'exécuteur de threads (pool de 5 workers max)
executor = ThreadPoolExecutor(max_workers=5)
