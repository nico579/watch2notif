"""Textes de l'interface (FR/EN) pour settings.py et l'icone de tray de
notifier.py. Meme esprit que le
bilinguisme des autres projets (blink2video, lidar2map) : anglais par
defaut, francais si la locale systeme le suggere, bascule manuelle
persistee dans config.json.
"""
import locale

STRINGS = {
    "window_title": {"en": "watch2notif - settings", "fr": "watch2notif - reglages"},
    "autostart_label": {"en": "Start automatically with the system", "fr": "Demarrer automatiquement avec le systeme"},
    "header_active": {"en": "Active", "fr": "Actif"},
    "header_kind": {"en": "Type", "fr": "Type"},
    "header_name": {"en": "Name", "fr": "Nom"},
    "header_url": {"en": "URL / source", "fr": "URL / source"},
    "header_interval": {"en": "Interval (s)", "fr": "Intervalle (s)"},
    "add_feed_button": {"en": "+ Add a source", "fr": "+ Ajouter une source"},
    "note_text": {
        "en": "Any RSS/Atom feed works, plus GitHub issues (owner/repo, public "
              "repos only, no auth needed). Reddit presets included "
              "(reddit.com/prefs/feeds), but you can add/remove freely. Some "
              "Reddit URLs carry a private token, avoid sharing screenshots "
              "of this panel. The interval field is prefilled based on the "
              "source type (GitHub issues default to a longer one, "
              "rate-limited to 60 requests/hour without a GITHUB_TOKEN); "
              "edit it freely per source.",
        "fr": "N'importe quel flux RSS/Atom fonctionne, plus les issues GitHub "
              "(owner/repo, repos publics uniquement, pas d'auth necessaire). "
              "Presets Reddit fournis (reddit.com/prefs/feeds), mais tu peux "
              "ajouter/retirer librement. Certaines URLs Reddit contiennent "
              "un token prive, evite de partager des captures de ce panneau. "
              "Le champ intervalle est "
              "prerempli selon le type de source (les issues GitHub ont un "
              "intervalle plus long par defaut, limitees a 60 requetes/heure "
              "sans GITHUB_TOKEN) ; modifiable librement par source.",
    },
    "save_button": {"en": "Save", "fr": "Sauvegarder"},
    "autostart_error_title": {"en": "Autostart error", "fr": "Erreur autostart"},
    "autostart_error_msg": {
        "en": "Settings saved, but autostart failed: {error}",
        "fr": "Reglages sauvegardes, mais l'autostart a echoue: {error}",
    },
    "ok_title": {"en": "OK", "fr": "OK"},
    "ok_msg": {"en": "Settings saved to config.json.", "fr": "Reglages sauvegardes dans config.json."},
    "tray_pause": {"en": "Pause polling", "fr": "Mettre en pause"},
    "tray_settings": {"en": "Settings...", "fr": "Reglages..."},
    "tray_update_available": {"en": "New version available (v{version})", "fr": "Nouvelle version disponible (v{version})"},
    "tray_update_install": {
        "en": "Install update v{version}...",
        "fr": "Installer la mise a jour v{version}...",
    },
    "tray_update_downloading": {
        "en": "Downloading update v{version}...",
        "fr": "Telechargement de la mise a jour v{version}...",
    },
    "tray_update_retry": {
        "en": "Retry update v{version}...",
        "fr": "Reessayer la mise a jour v{version}...",
    },
    "tray_update_view": {
        "en": "View update v{version}...",
        "fr": "Voir la mise a jour v{version}...",
    },
    "tray_help": {"en": "Help (GitHub)", "fr": "Aide (GitHub)"},
    "tray_quit": {"en": "Quit", "fr": "Quitter"},
    "update_notif_title": {"en": "watch2notif update available", "fr": "Mise a jour watch2notif disponible"},
    "update_notif_body": {
        "en": "Version {version} is out (currently running {current}). Open the tray menu to install it.",
        "fr": "La version {version} est sortie (version actuelle : {current}). Ouvre le menu du tray pour l'installer.",
    },
    "update_prompt_title": {
        "en": "Install the watch2notif update?",
        "fr": "Installer la mise a jour de watch2notif ?",
    },
    "update_prompt_body": {
        "en": "Version {version} is available (installed: {current}).\n\nwatch2notif will download it, verify it, restart, and keep your settings and notification history.",
        "fr": "La version {version} est disponible (installee : {current}).\n\nwatch2notif va la telecharger, la verifier, redemarrer et conserver tes reglages ainsi que l'historique des notifications.",
    },
    "update_install_button": {
        "en": "Download and install",
        "fr": "Telecharger et installer",
    },
    "update_later_button": {"en": "Later", "fr": "Plus tard"},
    "update_open_release_button": {
        "en": "Open release page",
        "fr": "Ouvrir la page de la release",
    },
    "update_close_button": {"en": "Close", "fr": "Fermer"},
    "update_source_title": {
        "en": "Automatic update unavailable",
        "fr": "Mise a jour automatique indisponible",
    },
    "update_source_body": {
        "en": "Automatic installation is available only in a supported packaged app. You can open the release page and update manually.",
        "fr": "L'installation automatique est disponible uniquement dans une application empaquetee compatible. Tu peux ouvrir la page de la release et faire la mise a jour manuellement.",
    },
    "update_progress_title": {
        "en": "Updating watch2notif",
        "fr": "Mise a jour de watch2notif",
    },
    "update_progress_body": {
        "en": "Downloading and verifying version {version}...\nwatch2notif remains active during preparation.",
        "fr": "Telechargement et verification de la version {version}...\nwatch2notif reste actif pendant la preparation.",
    },
    "update_error_title": {"en": "Update failed", "fr": "Echec de la mise a jour"},
    "update_error_body": {
        "en": "The update could not be installed. Nothing was changed and you can retry.\n\nReason: {error}",
        "fr": "La mise a jour n'a pas pu etre installee. Rien n'a ete modifie et tu peux reessayer.\n\nRaison : {error}",
    },
    "update_error_download": {
        "en": "The download failed. Check your connection and try again.",
        "fr": "Le telechargement a echoue. Verifie ta connexion puis reessaie.",
    },
    "update_error_integrity": {
        "en": "The downloaded bundle did not pass the integrity and safety checks.",
        "fr": "Le bundle telecharge n'a pas passe les controles d'integrite et de securite.",
    },
    "update_error_compatibility": {
        "en": "No valid update bundle is available for this system.",
        "fr": "Aucun bundle de mise a jour valide n'est disponible pour ce systeme.",
    },
    "update_error_installer": {
        "en": "The external updater could not be started safely.",
        "fr": "Le programme de mise a jour externe n'a pas pu etre demarre en securite.",
    },
    "update_error_generic": {
        "en": "An unexpected error occurred while preparing the update.",
        "fr": "Une erreur inattendue s'est produite pendant la preparation de la mise a jour.",
    },
}


def detect_default_lang() -> str:
    try:
        code = locale.getdefaultlocale()[0] or ""
    except Exception:
        code = ""
    return "fr" if code.lower().startswith("fr") else "en"


def t(key: str, lang: str, **kwargs) -> str:
    text = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    return text.format(**kwargs) if kwargs else text
