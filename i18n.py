"""Textes de l'interface (FR/EN) pour gui/ (page web de reglages/historique,
servie par notifier.py via nico579_commons.serveweb) et l'icone de tray. Meme esprit
que le bilinguisme des autres projets (blink2video, lidar2map) : anglais
par defaut, francais si la locale systeme le suggere, bascule manuelle
persistee dans config.json. Consomme aussi bien cote Python (tray) que
cote JS (gui/app.js, via GET /api/strings qui renvoie STRINGS tel quel).
"""
import locale

STRINGS = {
    "window_title": {"en": "watch2notif - settings", "fr": "watch2notif - reglages"},
    "header_pid": {"en": "Server PID {pid}", "fr": "PID serveur {pid}"},
    "tab_settings": {"en": "Settings", "fr": "Reglages"},
    "tab_history": {"en": "History", "fr": "Historique"},
    "autostart_label": {"en": "Start automatically with the system", "fr": "Demarrer automatiquement avec le systeme"},
    "header_active": {"en": "Active", "fr": "Actif"},
    "header_kind": {"en": "Type", "fr": "Type"},
    "header_name": {"en": "Name", "fr": "Nom"},
    "header_url": {"en": "URL / source", "fr": "URL / source"},
    "header_interval": {"en": "Interval (s)", "fr": "Intervalle (s)"},
    "add_feed_button": {"en": "+ Add a source", "fr": "+ Ajouter une source"},
    "note_text": {
        "en": "Any RSS/Atom feed works, plus GitHub issues (owner/repo, public "
              "repos, no auth needed), GitHub discussion replies "
              "(owner/repo#number, needs GITHUB_TOKEN), and YouTube video "
              "comments (needs YOUTUBE_API_KEY) - see README for details. "
              "Reddit presets included "
              "(reddit.com/prefs/feeds), but you can add/remove freely. Some "
              "Reddit URLs carry a private token, avoid sharing screenshots "
              "of this panel. The interval field is prefilled based on the "
              "source type (GitHub issues default to a longer one, "
              "rate-limited to 60 requests/hour without a GITHUB_TOKEN); "
              "edit it freely per source.",
        "fr": "N'importe quel flux RSS/Atom fonctionne, plus les issues GitHub "
              "(owner/repo, repos publics, pas d'auth necessaire), les "
              "reponses a une discussion GitHub (owner/repo#numero, "
              "necessite GITHUB_TOKEN), et les commentaires de video "
              "YouTube (necessite YOUTUBE_API_KEY) - voir le README pour le "
              "detail. Presets Reddit fournis (reddit.com/prefs/feeds), mais tu peux "
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
    # Le menu de l'icone vient, traduit, de nico579_commons.tray. Ces cles
    # tray_* gardent leur nom d'origine mais servent la page : case de
    # pause et bandeau de mise a jour.
    "tray_pause": {"en": "Pause polling", "fr": "Mettre en pause"},
    "help_link": {"en": "Help (GitHub)", "fr": "Aide (GitHub)"},
    "update_notif_title": {"en": "watch2notif update available", "fr": "Mise a jour watch2notif disponible"},
    "update_notif_body": {
        "en": "Version {version} is out (currently running {current}). Open the tray menu to install it.",
        "fr": "La version {version} est sortie (version actuelle : {current}). Ouvre le menu du tray pour l'installer.",
    },
    "history_window_title": {
        "en": "watch2notif - notification history",
        "fr": "watch2notif - historique des notifications",
    },
    "history_hint_text": {
        "en": "Double-click a row to open its link.",
        "fr": "Double-clique une ligne pour ouvrir son lien.",
    },
    "history_header_date": {"en": "Date", "fr": "Date"},
    "history_header_source": {"en": "Source", "fr": "Source"},
    "history_header_title": {"en": "Notification", "fr": "Notification"},
    "history_clear_button": {"en": "Clear history", "fr": "Vider l'historique"},
    "history_close_button": {"en": "Close", "fr": "Fermer"},
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
