# Home: My Cinema - Project Overview

Welcome to the **My Cinema** technical documentation. This project is a robust, containerized middleware designed to bridge Amazon Alexa voice commands with Kodi media center installations, specifically optimized for the *Fen Light* add-on via *TMDB Helper*.

---

## 🏗️ Technical Architecture

My Cinema operates as a Python-based microservice packaged in a Docker container. It acts as an abstraction layer between external voice inputs and your media player's internal JSON-RPC API.

### Core Stack
*   **Backend:** Python 3.9 (Flask)
*   **Deployment:** Docker (containerized for portability)
*   **Interfaces:** Web UI (Control Panel) & REST API (Alexa Webhook)
*   **External Integration:** 
    *   **Kodi JSON-RPC:** For transport control and media playback.
    *   **Trakt.tv API:** For synchronization and intelligent "Resume" features.
    *   **TMDB API:** For metadata lookups and media identification.
    *   **Management protocols:** ADB (Android) or SSH/SFTP (LibreELEC) for system maintenance.

### Key Components
*   **`app.py`:** The heart of the application. It handles the Flask routing, Alexa Intent dispatching, power management (Wake-on-LAN/ADB), and the background thread responsible for the **Fen Light Auto-Patcher**.
*   **Auto-Patcher Middleware:** A unique feature that monitors `kodi_utils.py` (located at `/sdcard/...` on Android or `/storage/...` on LibreELEC) to ensure external playback calls remain functional despite add-on updates.
*   **Web UI Control Panel:** Accessible on port `5000`, it provides real-time health checks for TMDB/Trakt, simplifies OAuth token generation, and allows manual power control of the target device.

---

## 🧠 The "Vibe Coding" Philosophy

**My Cinema** is a proud result of **"Vibe Coding"**. The entire architecture—from the decision to use a custom Patcher for *Fen Light* to the implementation of the dual-platform (Android/LibreELEC) power management system—was conceptualized and refined through an iterative, high-level conversation with the **Google Gemini** AI model. 

This approach allowed for rapid prototyping and clean, maintainable code structure, proving that complex automation projects can be successfully realized through natural language engineering.

---

## 🇫🇷 Présentation Générale

**My Cinema** est une solution middleware conteneurisée permettant de piloter votre installation **Kodi** (via l'add-on *Fen Light*) à la voix grâce à Alexa. Le projet repose sur une architecture **Flask** robuste et est conçu pour être déployé via **Docker**, garantissant une séparation nette entre l'environnement hôte et l'application.

### Architecture Technique
*   **Backend :** Python 3.9 propulsé par Flask, gérant les requêtes de l'API Alexa.
*   **Déploiement :** Docker (recommandé en `network_mode: host` pour le WoL).
*   **Patching Automatique :** Le service vérifie périodiquement l'intégrité de `plugin.video.fenlight/resources/lib/modules/kodi_utils.py` pour garantir la compatibilité des appels externes.
*   **Gestion d'énergie :** Support hybride :
    *   **Android (Nvidia Shield) :** Utilise `adb` (Android Debug Bridge) pour réveiller l'appareil et lancer l'activité Kodi.
    *   **LibreELEC/OpenELEC :** Utilise `paramiko` (SSH) pour les opérations systèmes.

### Philosophie "Vibe Coding"
Ce projet est une expérimentation pure en **"Vibe Coding"**. L'ensemble de l'architecture, de la gestion des tokens Trakt via l'interface Web (`/setup`) jusqu'à la logique de patch dynamique des fichiers Kodi, a été conçue par interaction directe avec **Google Gemini**. Cette méthode illustre la puissance du développement assisté par IA pour résoudre des problèmes techniques complexes de manière fluide et structurée.