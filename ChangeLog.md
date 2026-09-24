## [2.8.0] - 2026-09-24
- 🔑 **Connexion Trakt rétablie, par code d'appareil.** Un bouton dans les réglages affiche un code à saisir sur `trakt.tv/activate` : plus de Client ID ni de PIN à recopier. L'image embarque l'application Trakt de MyCinema, donc **l'utilisateur n'a aucune application à créer** ; `TRAKT_CLIENT_ID` / `TRAKT_CLIENT_SECRET` restent disponibles pour qui préfère la sienne.
- 🧠 **La reprise fonctionne appareil éteint.** La progression est demandée à Trakt en premier — seule source joignable quand la Shield dort, ce qui est précisément le moment où l'on demande à Alexa de reprendre une série — et le cache de l'addon Kodi prend le relais sans compte Trakt. Une source qui répond « rien à reprendre » fait autorité et n'est pas contredite par une source moins fiable.
- ⏱️ **Le jeton d'accès est renouvelé un jour avant son échéance**, au lieu d'attendre le premier 401 : en pleine requête vocale, il est trop tard pour rattraper quoi que ce soit dans le délai qu'Alexa accorde. Son expiration est désormais enregistrée (`expires_at`), ce qui n'était pas le cas.
- 🐛 **Mise à jour depuis une version à assistant PIN** : le `trakt_tokens.json` existant est fusionné par-dessus les variables d'environnement, si bien qu'un `client_id` périmé masquait celui embarqué — la page annonçait « compte connecté », la reprise prenait un 403 en silence, et la reconnexion échouait elle aussi faute d'utiliser la bonne application. Les réglages distinguent désormais « connecté », « autorisation refusée » et « vérification impossible », et la déconnexion repart des identifiants embarqués.
- ⚠️ **À savoir** : un compte Trakt gratuit est limité à **2 applications connectées**. Votre addon de streaming en occupe déjà une ; MyCinema prendra la seconde.
- 🐛 Correction : la section Trakt du README décrivait encore l'assistant PIN retiré en 2.7.1, qui n'existait plus.

## [2.7.1] - 2026-09-21
- 🗑️ **Assistant Trakt retiré des réglages** : créer une application API Trakt exige un abonnement VIP. L'API Trakt reste utilisable en secours par variables d'environnement (`TRAKT_CLIENT_ID`, `TRAKT_ACCESS_TOKEN`, ...) ou par un `trakt_tokens.json` existant.
- ⚙️ Nouveau réglage `PROGRESS_ADDON` (addon Kodi dont le cache Trakt donne l'épisode suivant) ; le dashboard affiche la source de reprise utilisée.

## [2.7.0] - 2026-09-21
- 📖 **Reprise sans clé API Trakt** : l'épisode suivant est lu dans le cache Trakt de l'addon Kodi (`PROGRESS_ADDON`, par défaut `plugin.video.pov`) rapatrié par ADB. L'API Trakt personnelle (réservée aux VIP depuis le 30/07/2026) ne sert plus que de secours ; un refus 401/403 est désormais signalé clairement.
- 🧩 **Players POV** : ajout de `pov_auto.json` et `pov_select.json` pour TMDb Helper.
- 🔌 **ADB** : une commande n'est plus rejouée après un délai dépassé (elle pouvait s'exécuter deux fois sur l'appareil).
- 🗑️ **Patcher Fen Light supprimé** : module, thread horaire, carte du dashboard, route `/trigger-patch`, intent `TriggerPatcherIntent` et workflow Gemini de mise à jour des signatures.

## [2.6.95] - 2026-09-20
- 🔐 **ADB** : la demande d'autorisation reste affichée 120 s sur la TV (5 s auparavant : impossible à accepter), état « ADB non autorisé » visible dans le dashboard et les logs.
- 🔌 **ADB** : connexion persistante et partagée (plus de nouvelle connexion toutes les 5 s), reconnexion automatique, accès sérialisé.

## [2.6.94] - 2026-05-05
- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v2.2.04

## [2.6.93] - 2026-05-02
- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v2.2.03

## [2.6.4] - 2026-05-01
- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v2.2.02

## [2.6.3] - 2026-04-30
- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v2.1.99

## [2.6.2] - 2026-04-16
- 🤖 Vibe Coding : Adaptation automatique du patch de lecture externe pour Fen Light v2.1.98

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
