# 🎬 My Cinema - An Amazon Skill for Kodi

![Version](https://img.shields.io/badge/Version-1.9.0-blue)
![Python](https://img.shields.io/badge/Python-3.9-blue?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Nvidia%20Shield-76B900?logo=nvidia&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A?logo=raspberry-pi&logoColor=white)
![Language](https://img.shields.io/badge/Language-English%20%2F%20French-blue)
![Flask](https://img.shields.io/badge/flask-%23000.svg?style=flat&logo=flask&logoColor=white)
![License](https://img.shields.io/github/license/ripleyxlr8/kodi-fenlight-alexa-skill?style=flat)
![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg?style=flat)
![Vibe Coding](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-orange?logo=buymeacoffee&logoColor=white)](https://buymeacoffee.com/ripleyxlr8)

**A dockerized Amazon Skill to start movies or series with voice control using your favorite Kodi video player add-on (like Fenlight) using TMBDHelper as an abstraction layer.**

This project features intelligent power management, TMDB series and movie lookup, Trakt.tv resume sync, and automated Fen Light add-on patching to allow use by external players (TMDB Helper). It fully supports **Android TV** (via ADB) and **LibreELEC** (via SSH).

## 🎥 Demo

See the skill in action (French language demo) :

[https://github.com/user-attachments/assets/da996a8d-55bf-4b13-b84a-542da01ceb5d](https://github.com/user-attachments/assets/da996a8d-55bf-4b13-b84a-542da01ceb5d)

## ✨ Key Features

* **🗣️ Multi-Language Voice Control:** Supports **English** and **French** natively. The skill detects the language of the request and responds accordingly.
* **⚡ Smart Power Management:** Automatically wakes up the Nvidia Shield (WoL/ADB) or uses Kodi's native HDMI-CEC (LibreELEC) before executing commands.
* **🧠 Trakt.tv Integration:** Smart resume features. Ask to *"Resume [Show]"* and it plays the specific *Next Up* episode from your Trakt history.
* **🔍 TMDB Search:** Accurate identification of media content (Movies vs Shows) with multi-language metadata support.
* **🛠️ Fen Light Auto-Patcher:** Includes a background scheduler that automatically patches the *Fen Light* addon to allow external calls (via TMDB Helper), ensuring playback works even after addon updates.
* **🎛️ Dual Playback Modes:** Choose between **Auto-Play** (instant launch) or **Source Select** (manual quality selection) via voice commands.

## 📱 Platform Comparison: Android TV vs LibreELEC

Because Android TV and LibreELEC handle background tasks differently, the skill adapts its behavior automatically based on your `TARGET_OS` configuration.

| Feature | Android TV (Nvidia Shield) | LibreELEC (Raspberry Pi) |
| :--- | :---: | :---: |
| **Voice Control (Movies & Shows)** | ✅ | ✅ |
| **Trakt.tv Sync (Smart Resume)** | ✅ | ✅ |
| **Dual Playback Modes (Auto/Manual)**| ✅ | ✅ |
| **Fen Light Auto-Patcher** | ✅ *(via ADB)* | ✅ *(via SSH)* |
| **Wake-on-LAN (WoL) Support** | ✅ | ❌ *(Not supported by RPI)* |
| **Force App Launch (Wake up Kodi)** | ✅ *(via ADB WAKEUP)* | ❌ *(But not needed since Kodi is the OS)* |
| **HDMI-CEC TV Wake-up** | ✅ *(via Android)* | ✅ *(via Kodi JSON-RPC)* |

## 🚀 Prerequisites

* **Software:** Kodi (v19 or newer).
* **Hardware Options:** * Nvidia Shield TV (or Android TV with **ADB debugging enabled**).
    * Raspberry Pi running LibreELEC (with **SSH enabled**).
* **Addons:**
    * `plugin.video.themoviedb.helper` (TMDB Helper).
    * `plugin.video.fenlight` (Fen Light or your favorite Kodi video player add-on).
* **Accounts:**
    * [TMDB API Key](https://www.themoviedb.org/documentation/api).
    * [Trakt.tv Client ID](https://trakt.tv/oauth/apps) (for API access).

## 📦 Installation

### 1. Kodi Configuration (TMDB Helper Players)
You need to add two custom players to TMDB Helper to handle the "Auto" and "Manual" modes.
Create these `.json` files in your Kodi userdata folder: 
`/Android/data/org.xbmc.kodi/files/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/players/` *(or `/storage/.kodi/...` on LibreELEC)*

* **fenlight_auto.json**: Standard URL for Fen Light playback (uses your default settings).
* **fenlight_select.json**: Same URL but with `&source_select=true` appended to force the source list.

You can create you own file for your favorite Kodi video player.

### 2. Docker Deployment
This application is designed to run in a Docker container.

**Note on Network:** Using `network_mode: host` or a macvlan (like `br0`) is **highly recommended** if you are targeting Android TV to allow Wake-on-LAN packets to pass through.

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
      - PYTHONUNBUFFERED=1
      
      # --- SYSTEM CONFIG ---
      - TARGET_OS=android # 'android' or 'libreelec'
      
      # --- SSH CONFIG (For LibreELEC only) ---
      - SSH_USER=root
      - SSH_PASS=libreelec
      
      # --- TARGET DEVICE CONFIG ---
      - SHIELD_IP=192.168.1.x
      - SHIELD_MAC=AA:BB:CC:DD:EE:FF # Optional for LibreELEC
      
      # --- KODI CONFIG ---
      - KODI_PORT=8080
      - KODI_USER=kodi
      - KODI_PASS=kodi
      
      # --- API KEYS & SECURITY ---
      - TMDB_API_KEY=your_tmdb_api_key
      - ALEXA_SKILL_ID=amzn1.ask.skill.xxxx-xxxx-xxxx-xxxx
      
      # --- TRAKT.TV ---
      - TRAKT_CLIENT_ID=your_trakt_client_id
      - TRAKT_ACCESS_TOKEN=your_trakt_access_token
      - TRAKT_REFRESH_TOKEN=your_trakt_refresh_token

      # --- TMDB HELPER PLAYERS ---
      - PLAYER_DEFAULT=fenlight_auto.json
      - PLAYER_SELECT=fenlight_select.json
      
      - DEBUG_MODE=false
```

### 3. Alexa Skill Setup
1.  Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) and create a **Custom Skill**.
2.  **Invocation Name:** Choose something simple like "my cinema" (EN) or "mon cinéma" (FR).
3.  **Endpoint:** Point it to your server's public HTTPS URL (e.g., using Cloudflare Tunnel): 
    `https://your-domain.com/alexa-webhook`
4.  **Interaction Model:** Create the Intents (`PlayMovieIntent`, `PlayTVShowIntent`, `ResumeTVShowIntent`) using the utterance lists provided in this repository's `speech_assets` folder.
5.  **Slots:** Ensure you create a slot type named `SourceMode` to handle manual selection requests (values: "manually", "select source", "avec choix", etc.).

### 4. 🔑 Trakt.tv Authentication Guide

To use the Smart Resume feature, the skill needs access to your Trakt.tv account history. You will need to provide 4 specific keys in your Docker configuration (`TRAKT_CLIENT_ID`, `TRAKT_CLIENT_SECRET`, `TRAKT_ACCESS_TOKEN`, and `TRAKT_REFRESH_TOKEN`). 

Since this app runs locally, you must manually generate the initial tokens once. The skill will then automatically handle the future token renewals.

**Step 1: Get your Client ID and Client Secret**
1. Go to your [Trakt.tv API Apps](https://trakt.tv/oauth/apps) and click **New Application**.
2. Name it whatever you like (e.g., "My Cinema Alexa").
3. In the **Redirect URI** field, you **must** enter exactly: `urn:ietf:wg:oauth:2.0:oob`
4. Save the app. Trakt will now display your **Client ID** and **Client Secret**.

**Step 2: Get your PIN Code**
1. Open a new browser tab and paste the following URL, replacing `YOUR_CLIENT_ID` with the ID from Step 1:
   `https://trakt.tv/oauth/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob`
2. Click **Yes** to authorize your newly created app to access your account.
3. Trakt will provide a long alphanumeric **PIN Code**. Copy it.

**Step 3: Generate your Access and Refresh Tokens**
Open a terminal (Linux/macOS) or PowerShell/Command Prompt (Windows) and run this `curl` command. Make sure to replace the placeholder values with your actual PIN, Client ID, and Client Secret:

```bash
curl -X POST https://api.trakt.tv/oauth/token \
-H "Content-Type: application/json" \
-d '{
  "code": "YOUR_PIN_CODE",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
  "grant_type": "authorization_code"
}'
```
Result: The API will return a JSON response containing your "access_token" and "refresh_token". Copy these two values into your docker-compose.yaml (or Unraid template) along with your Client ID and Secret. You're all set forever!

## 🗣️ Usage Examples

The skill automatically responds in the language used to invoke it.

| Action | English Command | Commande Française |
| :--- | :--- | :--- |
| **Launch a Movie** | *"Alexa, ask My Cinema to play Avatar."* | *"Alexa, demande à Mon Cinéma de lancer Avatar."* |
| **Launch a Show** | *"Alexa, ask My Cinema to play The Witcher."* | *"Alexa, demande à Mon Cinéma de lancer The Witcher."* |
| **Specific Episode** | *"Alexa, ask My Cinema to play Friends, Season 5 Episode 10."* | *"Alexa, demande à Mon Cinéma de lancer Friends, Saison 5 Épisode 10."* |
| **Resume (Trakt)** | *"Alexa, ask My Cinema to resume Breaking Bad."* | *"Alexa, demande à Mon Cinéma de reprendre Breaking Bad."* |
| **Manual Select** | *"Alexa, ask My Cinema to play Inception **manually**."* | *"Alexa, demande à Mon Cinéma de lancer Inception **avec choix**."* |

## 🔧 Technical Details

### The Fen Light Auto-Patcher
Fen Light restricts external playback calls by default. This middleware includes a background thread that automatically patches the restrictive logic.
* **On Android TV:** Uses ADB `pull` and `push` to modify the files on the internal `/sdcard` storage.
* **On LibreELEC:** Uses Python's `paramiko` library to establish an SSH/SFTP connection and patch the files on the Raspberry Pi's `/storage` partition.

### Localization System
The application uses a `translations.json` file to store responses. It parses the locale received in the Alexa JSON request (e.g., `fr-FR` or `en-US`) and serves the appropriate response string. Metadata from TMDB is also fetched in the requested language.

### Power Management (Android Only)
If targeting Android TV, the script uses a hybrid approach to ensure the Shield is ready before sending the command:
1.  **Wake-on-LAN:** Sends a magic packet to wake the network interface.
2.  **ADB Wake:** Sends standard Android `WAKEUP` key events via ADB.
3.  **ADB Start:** Forces the Kodi activity to launch if it's not already in the foreground.

## 🤖 Vibe Coding & Credits

**This project is a pure "Vibe Coding" experiment.**

It was entirely architected, debugged, and refined through a continuous natural language dialogue with **Google Gemini**. No manual coding was performed; the human acted as the conductor, and the AI as the expert developer.

---
**Enjoying this project?** If this tool helps you tame your Home Cinema, consider supporting the updates!  
[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/ripleyxlr8)

## 📄 License
[MIT License](LICENSE)
