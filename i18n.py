"""Textes de l'interface (FR/EN) pour settings.py et l'icone de tray de
notifier.py. Meme esprit que le
bilinguisme des autres projets (blink2video, lidar2map) : anglais par
defaut, francais si la locale systeme le suggere, bascule manuelle
persistee dans config.json.
"""
import locale

STRINGS = {
    "window_title": {"en": "watch2notif - settings", "fr": "watch2notif - reglages"},
    "interval_label": {"en": "Default polling interval (seconds):", "fr": "Intervalle de polling par defaut (secondes) :"},
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
              "(reddit.com/prefs/feeds), but you can add/remove freely. "
              "URLs are masked on screen when they contain a private token. "
              "Leave the interval blank to use the default above; GitHub issues "
              "are rate-limited to 60 requests/hour without a GITHUB_TOKEN, so "
              "prefer a longer interval for that type.",
        "fr": "N'importe quel flux RSS/Atom fonctionne, plus les issues GitHub "
              "(owner/repo, repos publics uniquement, pas d'auth necessaire). "
              "Presets Reddit fournis (reddit.com/prefs/feeds), mais tu peux "
              "ajouter/retirer librement. Les URLs sont masquees a l'ecran si "
              "elles contiennent un token prive. Laisse l'intervalle vide pour "
              "utiliser celui par defaut ci-dessus ; les issues GitHub sont "
              "limitees a 60 requetes/heure sans GITHUB_TOKEN, prefere un "
              "intervalle plus long pour ce type.",
    },
    "save_button": {"en": "Save", "fr": "Sauvegarder"},
    "error_title": {"en": "Error", "fr": "Erreur"},
    "error_interval_msg": {
        "en": "Invalid interval (integer >= 5 seconds).",
        "fr": "Intervalle invalide (entier >= 5 secondes).",
    },
    "autostart_error_title": {"en": "Autostart error", "fr": "Erreur autostart"},
    "autostart_error_msg": {
        "en": "Settings saved, but autostart failed: {error}",
        "fr": "Reglages sauvegardes, mais l'autostart a echoue: {error}",
    },
    "ok_title": {"en": "OK", "fr": "OK"},
    "ok_msg": {"en": "Settings saved to config.json.", "fr": "Reglages sauvegardes dans config.json."},
    "tray_pause": {"en": "Pause polling", "fr": "Mettre en pause"},
    "tray_open_config": {"en": "Open config file", "fr": "Ouvrir le fichier de configuration"},
    "tray_update_available": {"en": "New version available (v{version})", "fr": "Nouvelle version disponible (v{version})"},
    "tray_quit": {"en": "Quit", "fr": "Quitter"},
    "update_notif_title": {"en": "watch2notif update available", "fr": "Mise a jour watch2notif disponible"},
    "update_notif_body": {
        "en": "Version {version} is out (currently running {current}). Click to see the release.",
        "fr": "La version {version} est sortie (version actuelle : {current}). Clique pour voir la release.",
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
