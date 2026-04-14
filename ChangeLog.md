## [2.4.2] - 2026-04-14
- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v2.1.97

# Changelog

Toutes les modifications notables de ce projet seront documentées dans ce fichier.

## [2.4.0] - 2026-04-14
- 🏗️ **Refactorisation Modulaire** : Division du projet en modules (`config`, `logic`, `patcher`) pour corriger le problème de "God Object".
- 🚀 **Performance** : Allègement du point d'entrée `app.py`.
- 🤖 **Vibe Coding** : Adaptation du script d'auto-patching pour supporter la nouvelle structure modulaire.

## [2.0.0] - 2026-04-13
- ✨ **Web UI Dashboard** : Ajout d'une interface web moderne (Tailwind CSS) pour monitorer l'état du système.
- 🔑 **Trakt Setup Wizard** : Intégration d'un formulaire de configuration Trakt.tv pour générer les tokens automatiquement sans ligne de commande.
- 🔒 **Security** : Ajout d'une Secret Key Flask pour la gestion des sessions Web.
- 🛠️ **Refactorisation** : Amélioration de la gestion de la persistance des tokens (priorité au stockage local sur les variables d'environnement).

## [1.9.0] - 2026-04-11
- 🐧 **Support OS** : Ajout du support d'OpenELEC et LibreELEC sur Raspberry Pi (communication via SSH).
- 📺 **Android TV** : Optimisation du support Android TV (Nvidia Shield) via ADB avec gestion de l'alimentation hybride (Wake-on-LAN + ADB WAKEUP).

## [1.8.0] - 2026-04-11
- 🔒 **Sécurité** : Ajout de la validation de l'ID de la Skill Alexa (`ALEXA_SKILL_ID`) pour sécuriser le webhook contre les appels malveillants.

## [1.7.6] - 2026-04-11
- 🤖 **Vibe Coding** : Adaptation automatique du patch de lecture externe pour Fen Light v2.1.96.
