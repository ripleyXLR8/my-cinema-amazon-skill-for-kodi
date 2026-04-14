# 🎬 My Cinema - An Alexa Skill for FenLight AM (or your favorite Kodi player)

![Version](https://img.shields.io/badge/Version-2.3.2-blue)
![Python](https://img.shields.io/badge/Python-3.9-blue?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
[![Unraid Ready](https://img.shields.io/badge/Unraid-Community%20Applications-orange.svg)](https://forums.unraid.net/topic/197994-support-my-cinema-an-alexa-skill-to-control-fenlight-running-on-your-kodi-shield-based-media-center/)
![Platform](https://img.shields.io/badge/Platform-Nvidia%20Shield-76B900?logo=nvidia&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A?logo=raspberry-pi&logoColor=white)
![Language](https://img.shields.io/badge/Language-English%20%2F%20French-blue)
![License](https://img.shields.io/github/license/ripleyxlr8/kodi-fenlight-alexa-skill?style=flat)
![Vibe Coding](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-orange?logo=buymeacoffee&logoColor=white)](https://buymeacoffee.com/ripleyxlr8)

**This container is an Alexa Skill allowing voice control for your favorite Kodi Player (for example FenLight AM). It is specifically optimized to search, play, and resume media using the FenLight AM add-on via TMDB Helper on devices like Nvidia Shield or Raspberry Pi.**

**This container can be installed directly using docker or on your Unraid Server directly through Community Applications (CA).**

This dockerized solution acts as a middleware bridge, featuring a modern **Web UI Control Panel**, intelligent power management, and an automated patcher to ensure Fen Light remains compatible with external playback calls.

## 🎥 Demo

See the skill in action (French language demo):

https://github.com/user-attachments/assets/da996a8d-55bf-4b13-b84a-542da01ceb5d

## ✨ Key Features

* **🖥️ Web UI Control Panel:** A real-time dashboard to monitor your Kodi connection, TMDB API status, Fen Light patcher health, and Trakt.tv synchronization.
* **🔑 Visual Trakt Setup:** Easily link your Trakt.tv account through a dedicated web wizard—no manual command line required.
* **🗣️ Multi-Language Support:** Full native support for **English** and **French** commands and responses.
* **⚡ Smart Power Management:** Automatically handles device wake-up (WoL/ADB for Shield) or system commands (SSH for LibreELEC) before playback.
* **🧠 Trakt.tv Resume:** Ask Alexa to *"Resume [Show]"* to instantly play your *Next Up* episode based on your Trakt history.
* **🔍 TMDB Integration:** Accurate identification of movies and TV shows with rich metadata support.
* **🛠️ Fen Light Auto-Patcher:** A background service that automatically updates the *Fen Light* addon logic to allow external integration, surviving addon updates.
* **🔒 Secure Webhook:** Cryptographic validation of Alexa requests to ensure only your authorized skill can control your media center.

## 📱 Platform Comparison

**This container has initialy been developped to control Kodi and Fenlight AM running on the NVidia Shield platform but it can be used to control in conjunction with LibreElec / OpenElec running on a Raspberry Pi.**

Here is a quick comparison of the features available on the different platform :

| Feature | Android TV (Nvidia Shield) | LibreELEC / OpenELEC |
| :--- | :--- | :--- |
| **Voice Control** | ✅ | ✅ |
| **Trakt.tv Sync** | ✅ | ✅ |
| **Web UI Dashboard** | ✅ | ✅ |
| **Fen Light Auto-Patcher** | ✅ *(via ADB)* | ✅ *(via SSH)* |
| **Wake-on-LAN Support** | ✅ | ❌ |
| **HDMI-CEC TV Wake-up** | ✅ *(via Android)* | ✅ *(via JSON-RPC)* |

## 🚀 Installation & Setup

### 1. Kodi Configuration (TMDB Helper Players)

Install your favorite Kodi player like Fenlight AM. (use google to find a tutorial on how to install and configure Fenlight AM) and the TMDB Helper Add-On.

Create the following `.json` files in your Kodi `userdata/addon_data/plugin.video.themoviedb.helper/players/` folder:

* **fenlight_auto.json**: For standard, hands-free playback.
* **fenlight_select.json**: For playback with a manual source selection menu.

### 2. Docker Deployment
Deployment via Docker Compose is recommended. Use `network_mode: host` for the best results with Wake-on-LAN. The container includes a healthcheck specifically optimized for Docker environments like Unraid.

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
      - SSH_USER=root
      - SSH_PASS=libreelec
      - SHIELD_IP=192.168.1.x
      - SHIELD_MAC=AA:BB:CC:DD:EE:FF
      - TMDB_API_KEY=your_tmdb_api_key
      - ALEXA_SKILL_ID=amzn1.ask.skill.xxxx
      - KODI_PORT=8080
      - KODI_USER=kodi
      - KODI_PASS=kodi
```

### 3. 🔑 Trakt.tv Configuration (The Easy Way)

1. With the container running, go to **`http://YOUR_SERVER_IP:5000/settings`** in your browser.
2. Enter your Trakt **Client ID** and **Client Secret**.
3. Click **"Get PIN"**, authorize the app, and copy the code.
4. Paste the PIN and click **"Generate Tokens"** to complete the link.

### 4. 🎙️ Alexa Skill Setup

To bridge your voice commands to the backend, follow these steps in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask):

1. **Create Skill:** Create a new **Custom Skill**.
2. **Interaction Model:**
    * Go to the **JSON Editor** section.
    * Import the provided JSON file from the `/alexa_speech_assets` folder (e.g., `FR.json` or `US.json`).
    * This will automatically create the necessary Intents (`PlayMovieIntent`, `ResumeTVShowIntent`, etc.) and Slots (`MovieName`, `ShowName`, `SourceMode`).
3. **Endpoint Configuration:**
    * In the **Endpoint** tab, select **HTTPS**.
    * Enter your public URL followed by `/alexa-webhook` (e.g., `https://your-domain.com/alexa-webhook`).
    * **Note:** A valid SSL certificate is required. If using a reverse proxy, ensure it points to port `5000`.
4. **Security (Skill ID):**
    * Copy your **Your Skill ID** (e.g., `amzn1.ask.skill.xxxx`) from the console.
    * Add it to your `docker-compose.yaml` under the `ALEXA_SKILL_ID` environment variable. The backend will reject any request not matching this ID.

## 🗣️ Usage Examples

| Action | English Command | Commande Française |
| :--- | :--- | :--- |
| **Play Movie** | *"Alexa, ask My Cinema to play Inception."* | *"Alexa, demande à Mon Cinéma de lancer Inception."* |
| **Play Show** | *"Alexa, ask My Cinema to play The Witcher."* | *"Alexa, demande à Mon Cinéma de lancer The Witcher."* |
| **Resume** | *"Alexa, ask My Cinema to resume Breaking Bad."* | *"Alexa, demande à Mon Cinéma de reprendre Breaking Bad."* |
| **Manual Select** | *"Alexa, ask My Cinema to play Avatar **manually**."* | *"Alexa, demande à Mon Cinéma de lancer Avatar **avec choix**."* |

## 🔧 Technical Details

### The Fen Light Auto-Patcher
Fen Light restricts external playback calls by default. This middleware includes a background thread that automatically patches the restrictive logic.
* **On Android TV:** Uses ADB `pull` and `push` to modify the files on the internal `/sdcard` storage.
* **On LibreELEC / OpenELEC:** Uses Python's `paramiko` library to establish an SSH/SFTP connection and patch the files on the Raspberry Pi's `/storage` partition.

## 🤖 Vibe Coding & Credits

**This project is a pure "Vibe Coding" experiment.**
The entire architecture and feature set were refined through natural language dialogue with **Google Gemini**.

---
**Enjoying this project?** [![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/ripleyxlr8)

## 📄 License
[MIT License](LICENSE)
