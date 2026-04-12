# 🎬 My Cinema - An Amazon Skill for Kodi

![Version](https://img.shields.io/badge/Version-2.0.0-blue)
![Python](https://img.shields.io/badge/Python-3.9-blue?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Nvidia%20Shield-76B900?logo=nvidia&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A?logo=raspberry-pi&logoColor=white)
![Language](https://img.shields.io/badge/Language-English%20%2F%20French-blue)
![Flask](https://img.shields.io/badge/flask-%23000.svg?style=flat&logo=flask&logoColor=white)
![License](https://img.shields.io/github/license/ripleyxlr8/kodi-fenlight-alexa-skill?style=flat)
![Vibe Coding](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-orange?logo=buymeacoffee&logoColor=white)](https://buymeacoffee.com/ripleyxlr8)

**A dockerized Amazon Skill to start movies or series with voice control using your favorite Kodi video player add-on (like Fenlight) using TMBDHelper as an abstraction layer.**

This project features a modern **Web UI Control Panel**, intelligent power management, TMDB series and movie lookup, Trakt.tv resume sync, and automated Fen Light add-on patching. It fully supports **Android TV** (via ADB) and **LibreELEC / OpenELEC** (via SSH).

## 🎥 Demo

See the skill in action (French language demo) :

https://github.com/user-attachments/assets/da996a8d-55bf-4b13-b84a-542da01ceb5d

## ✨ Key Features

* **🖥️ Web UI Control Panel (New v2.0):** A modern dashboard to monitor your Kodi connection, TMDB API status, and Trakt.tv synchronization in real-time.
* **🔑 Visual Trakt Setup:** No more manual `curl` commands! Link your Trakt.tv account directly through the web interface with a step-by-step wizard.
* **🗣️ Multi-Language Voice Control:** Supports **English** and **French** natively. The skill detects the language of the request and responds accordingly.
* **⚡ Smart Power Management:** Automatically wakes up the Nvidia Shield (WoL/ADB) or uses Kodi's native HDMI-CEC (LibreELEC / OpenELEC) before executing commands.
* **🧠 Trakt.tv Integration:** Smart resume features. Ask to *"Resume [Show]"* and it plays the specific *Next Up* episode from your Trakt history.
* **🔍 TMDB Search:** Accurate identification of media content (Movies vs Shows) with multi-language metadata support.
* **🛠️ Fen Light Auto-Patcher:** Includes a background scheduler that automatically patches the *Fen Light* addon to allow external calls (via TMDB Helper), ensuring playback works even after addon updates.

## 📱 Platform Comparison: Android TV vs LibreELEC / OpenELEC

| Feature | Android TV (Nvidia Shield) | LibreELEC / OpenELEC |
| :--- | :---: | :---: |
| **Voice Control (Movies & Shows)** | ✅ | ✅ |
| **Trakt.tv Sync (Smart Resume)** | ✅ | ✅ |
| **Web UI Dashboard** | ✅ | ✅ |
| **Fen Light Auto-Patcher** | ✅ *(via ADB)* | ✅ *(via SSH)* |
| **Wake-on-LAN (WoL) Support** | ✅ | ❌ *(Not supported by RPI)* |
| **Force App Launch (Wake up Kodi)** | ✅ *(via ADB WAKEUP)* | ❌ *(Not needed)* |
| **HDMI-CEC TV Wake-up** | ✅ *(via Android)* | ✅ *(via Kodi JSON-RPC)* |

## 🚀 Installation & Setup

### 1. Kodi Configuration (TMDB Helper Players)
You need to add two custom players to TMDB Helper to handle the "Auto" and "Manual" modes.
Create these `.json` files in your Kodi userdata folder: 
`/Android/data/org.xbmc.kodi/files/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/players/` *(or `/storage/.kodi/...` on LibreELEC)*

* **fenlight_auto.json**: Standard URL for Fen Light playback (uses your default settings).
* **fenlight_select.json**: Same URL but with `&autoplay=false` (or source_select) to force the source list.

### 2. Docker Deployment
This application is designed to run in a Docker container. Using `network_mode: host` is **highly recommended** for Wake-on-LAN support.

**docker-compose.yaml:**
```yaml
version: '3.8'

services:
  kodi-alexa-skill:
    image: ghcr.io/ripleyxlr8/my-cinema-amazon-skill-for-kodi:latest
    container_name: kodi-fenlight-alexa-skill
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./adb_keys:/root/.android
    environment:
      - TZ=Europe/Paris
      - TARGET_OS=android # 'android' or 'libreelec'
      - SHIELD_IP=192.168.1.x
      - SHIELD_MAC=AA:BB:CC:DD:EE:FF
      - TMDB_API_KEY=your_tmdb_api_key
      - ALEXA_SKILL_ID=amzn1.ask.skill.xxxx
      - KODI_PORT=8080
      - KODI_USER=kodi
      - KODI_PASS=kodi
```

### Environment Variables Summary

| Variable | Description | Required | Default / Example |
| :--- | :--- | :---: | :--- |
| `TARGET_OS` | Target operating system (`android` or `libreelec`). | Yes | `android` |
| `SHIELD_IP` | IP address of your Nvidia Shield or Raspberry Pi. | Yes | `192.168.1.x` |
| `SHIELD_MAC` | MAC address for Wake-on-LAN (Android only). | No | `AA:BB:CC:DD:EE:FF` |
| `SSH_USER` | SSH username (LibreELEC/OpenELEC only). | No | `root` |
| `SSH_PASS` | SSH password (LibreELEC/OpenELEC only). | No | `libreelec` |
| `KODI_PORT` | Kodi Web Server API Port. | Yes | `8080` |
| `KODI_USER` | Kodi Web Server Username. | No | `kodi` |
| `KODI_PASS` | Kodi Web Server Password. | No | `kodi` |
| `TMDB_API_KEY` | Your TMDB (TheMovieDB) API Key. | Yes | - |
| `ALEXA_SKILL_ID` | Your Custom Alexa Skill ID (Secures the webhook). | Yes | `amzn1.ask.skill...` |
| `PLAYER_DEFAULT` | Default TMDB Helper player filename. | No | `fenlight_auto.json` |
| `PLAYER_SELECT` | Manual source TMDB Helper player filename. | No | `fenlight_select.json` |
| `DEBUG_MODE` | Enable verbose/debug logs (`true` or `false`). | No | `false` |
| `TZ` | Container Timezone. | No | `Europe/Paris` |

*(Note: Trakt API variables are now configured directly via the Web UI.)*

### 3. 🔑 Trakt.tv Configuration (The Easy Way)
1.  Once the container is running, open your browser at `http://YOUR_SERVER_IP:5000/setup`.
2.  Enter your Trakt **Client ID** and **Client Secret**.
3.  Click **"Get PIN"**, authorize the app on Trakt, and copy the resulting PIN code.
4.  Paste the PIN and click **"Generate Tokens"**. Your skill is now linked!

### 4. Alexa Skill Setup
1.  Create a **Custom Skill** in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2.  Set the **Endpoint** to your public HTTPS URL: `https://your-domain.com/alexa-webhook`.
3.  Interaction models are provided in the `alexa_speech_assets` folder.

## 🗣️ Usage Examples

| Action | English Command | Commande Française |
| :--- | :--- | :--- |
| **Launch a Movie** | *"Alexa, ask My Cinema to play Avatar."* | *"Alexa, demande à Mon Cinéma de lancer Avatar."* |
| **Launch a Show** | *"Alexa, ask My Cinema to play The Witcher."* | *"Alexa, demande à Mon Cinéma de lancer The Witcher."* |
| **Resume (Trakt)** | *"Alexa, ask My Cinema to resume Breaking Bad."* | *"Alexa, demande à Mon Cinéma de reprendre Breaking Bad."* |
| **Manual Select** | *"Alexa, ask My Cinema to play Inception **manually**."* | *"Alexa, demande à Mon Cinéma de lancer Inception **avec choix**."* |

## 🔧 Technical Details

### The Fen Light Auto-Patcher
Fen Light restricts external playback calls by default. This middleware includes a background thread that automatically patches the restrictive logic.
* **On Android TV:** Uses ADB `pull` and `push` to modify the files on the internal `/sdcard` storage.
* **On LibreELEC / OpenELEC:** Uses Python's `paramiko` library to establish an SSH/SFTP connection and patch the files on the Raspberry Pi's `/storage` partition.

### Power Management (Android Only)
If targeting Android TV, the script uses a hybrid approach to ensure the Shield is ready before sending the command:
1.  **Wake-on-LAN:** Sends a magic packet to wake the network interface.
2.  **ADB Wake:** Sends standard Android `WAKEUP` key events via ADB.
3.  **ADB Start:** Forces the Kodi activity to launch if it's not already in the foreground.

## 🤖 Vibe Coding & Credits

**This project is a pure "Vibe Coding" experiment.**
Entirely architected and refined through natural language dialogue with **Google Gemini**.

---
**Enjoying this project?** [![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/ripleyxlr8)

## 📄 License
[MIT License](LICENSE)
