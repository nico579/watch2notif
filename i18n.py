"""Textes de l'interface (FR/EN) pour gui/ (page web de reglages/historique,
servie par notifier.py via nico579_commons.serveweb) et l'icone de tray. Meme esprit
que le bilinguisme des autres projets (blink2video, lidar2map) : anglais
par defaut, francais si la locale systeme le suggere, bascule manuelle
persistee dans config.json. Consomme aussi bien cote Python (tray) que
cote JS (gui/app.js, via GET /api/strings qui renvoie STRINGS tel quel).

Le francais s'ecrit avec ses accents et vouvoie : la page cotoie les textes
de nico579_commons (bandeau de mise a jour, panneau Reglages, menu de
l'icone), accentues, et un melange se voyait d'une ligne a l'autre.
"""
import functools
import os
import re
import subprocess
import sys

STRINGS = {
    "window_title": {"en": "watch2notif - settings", "fr": "watch2notif - réglages"},
    "header_pid": {"en": "Server PID {pid}", "fr": "PID serveur {pid}"},
    "tab_feeds": {"en": "Feeds", "fr": "Flux"},
    "tab_history": {"en": "History", "fr": "Historique"},
    "header_active": {"en": "Active", "fr": "Actif"},
    "header_kind": {"en": "Type", "fr": "Type"},
    "header_name": {"en": "Name", "fr": "Nom"},
    "header_url": {"en": "URL / source", "fr": "URL / source"},
    "header_interval": {"en": "Interval (s)", "fr": "Intervalle (s)"},
    "add_feed_button": {"en": "+ Add a source", "fr": "+ Ajouter une source"},
    "filter_button": {"en": "AI filter", "fr": "Filtre IA"},
    "filter_button_title": {
        "en": "Only notify the entries an AI model judges relevant to your instructions "
              "(needs ANTHROPIC_API_KEY, see README)",
        "fr": "Ne notifier que les entrées qu'un modèle d'IA juge conformes à votre consigne "
              "(demande ANTHROPIC_API_KEY, voir README)",
    },
    "filter_key_missing": {
        "en": "No ANTHROPIC_API_KEY on this computer: this filter will not sort anything, "
              "every entry is notified. How to get one and set it:",
        "fr": "Pas de clé ANTHROPIC_API_KEY sur cet ordinateur : ce filtre ne triera rien, "
              "toutes les entrées seront notifiées. Comment l'obtenir et la poser :",
    },
    "filter_key_url": {
        "en": "https://github.com/nico579/watch2notif#ai-filter-optional",
        "fr": "https://github.com/nico579/watch2notif/blob/master/README.fr.md#filtre-ia-facultatif",
    },
    "filter_placeholder": {
        "en": "Instructions for the AI filter: which entries deserve a notification? "
              "Empty = notify everything.",
        "fr": "Consigne du filtre IA : quelles entrées méritent une notification ? "
              "Vide = tout notifier.",
    },
    "note_text": {
        "en": "Any RSS/Atom feed works, plus GitHub issues (owner/repo, public "
              "repos, no auth needed), GitHub discussion replies "
              "(owner/repo#number) and GitHub Sponsors (your login), which "
              "need GITHUB_TOKEN, and YouTube video comments (needs "
              "YOUTUBE_API_KEY); see the README for details. Some feed URLs, "
              "Reddit's private feeds for instance, carry a private token: "
              "avoid sharing screenshots of this panel. The interval is "
              "prefilled from the source type (longer for GitHub, limited to "
              "60 requests/hour without a GITHUB_TOKEN) and can be set per "
              "source, from 5 seconds to a week.",
        "fr": "N'importe quel flux RSS/Atom fonctionne, plus les issues GitHub "
              "(owner/repo, dépôts publics, sans authentification), les "
              "réponses à une discussion GitHub (owner/repo#numéro) et GitHub "
              "Sponsors (votre identifiant), qui demandent GITHUB_TOKEN, et "
              "les commentaires d'une vidéo YouTube (demande YOUTUBE_API_KEY) ; "
              "voir le README pour le détail. Certaines URLs de flux, comme "
              "les flux privés de Reddit, contiennent un token privé : évitez "
              "de partager des captures de ce panneau. L'intervalle est "
              "prérempli selon le type de source (plus long pour GitHub, "
              "limité à 60 requêtes/heure sans GITHUB_TOKEN) et se règle par "
              "source, de 5 secondes à une semaine.",
    },
    "save_button": {"en": "Save", "fr": "Sauvegarder"},
    "config_import_button": {"en": "Import JSON", "fr": "Importer un JSON"},
    "config_export_button": {"en": "Export JSON", "fr": "Exporter un JSON"},
    "config_transfer_note": {
        "en": "Share source settings with Android using a JSON file. Claude rules are preserved. API keys, history and system settings stay on each device. Feed URLs can contain private tokens: keep the file private.",
        "fr": "Transférez les sources vers Android avec un fichier JSON. Les consignes Claude sont conservées. Les clés API, l'historique et les réglages système restent sur chaque appareil. Les URLs de flux peuvent contenir des tokens privés : gardez le fichier privé.",
    },
    "config_import_confirm": {
        "en": "Replace the sources displayed here with {count} imported sources? Click Save afterwards to apply them.",
        "fr": "Remplacer les sources affichées par les {count} sources importées ? Cliquez ensuite sur Sauvegarder pour les appliquer.",
    },
    "config_imported": {"en": "Sources imported. Click Save to apply them.", "fr": "Sources importées. Cliquez sur Sauvegarder pour les appliquer."},
    "config_exported": {"en": "Configuration exported.", "fr": "Configuration exportée."},
    "config_invalid": {"en": "Invalid configuration. No settings changed.", "fr": "Configuration invalide. Aucun réglage modifié."},
    "pair_send_button": {"en": "Send to phone", "fr": "Envoyer vers le téléphone"},
    "pair_title": {"en": "Pair your phone", "fr": "Appairer le téléphone"},
    "pair_note": {
        "en": "Connect both devices to the same local network. In Android Settings, tap Scan the PC QR. Sources, Claude rules and API keys are encrypted; the decryption key is only in this QR. Treat the QR as private.",
        "fr": "Connectez les deux appareils au même réseau local. Dans les Réglages Android, touchez Scanner le QR du PC. Les sources, consignes Claude et clés API sont chiffrées ; la clé de déchiffrement est uniquement dans ce QR. Gardez ce QR privé.",
    },
    "pair_ready": {"en": "PC: {address} - expires in {seconds} s", "fr": "PC : {address} - expire dans {seconds} s"},
    "pair_address_label": {"en": "PC network connected to the phone", "fr": "Réseau du PC relié au téléphone"},
    "pair_preparing": {"en": "Preparing local access…", "fr": "Préparation de l'accès local…"},
    "pair_public_network": {
        "en": "Windows marks this network as Public. Its firewall may block the phone. Use Allow local transfer below if needed.",
        "fr": "Windows classe ce réseau comme Public. Son pare-feu peut bloquer le téléphone. Utilisez Autoriser le transfert local ci-dessous si nécessaire.",
    },
    "pair_allow_button": {"en": "Allow local transfer", "fr": "Autoriser le transfert local"},
    "pair_renew_button": {"en": "Generate a new QR", "fr": "Générer un nouveau QR"},
    "pair_firewall_note": {
        "en": "This button requests Windows administrator consent. It replaces watch2notif's general TCP block on Public networks with a permission limited to this app, the selected PC address and local-subnet peers. The rule remains saved; the encrypted transfer port closes after use or 2 minutes.",
        "fr": "Ce bouton demande le consentement administrateur Windows. Il remplace le blocage TCP général de watch2notif sur les réseaux Publics par une autorisation limitée à cette application, à l'adresse PC choisie et au sous-réseau local. La règle reste enregistrée ; le port du transfert chiffré se ferme après usage ou 2 minutes.",
    },
    "pair_firewall_wait": {"en": "Accept the Windows administrator prompt…", "fr": "Validez la demande administrateur de Windows…"},
    "pair_firewall_allowed": {"en": "Local transfer allowed. Scan the new QR. Phone connectivity still needs to be checked.", "fr": "Transfert local autorisé. Scannez le nouveau QR. La connexion du téléphone reste à vérifier."},
    "pair_firewall_blocked": {
        "en": "A firewall block rule takes priority and cannot be replaced by this button. Check watch2notif in Windows Firewall.",
        "fr": "Une règle de blocage du pare-feu est prioritaire et ne peut pas être remplacée par ce bouton. Vérifiez watch2notif dans le pare-feu Windows.",
    },
    "pair_firewall_detected": {"en": "Windows explicitly blocks watch2notif on Public networks. Allow local transfer to replace this block with a scoped permission.", "fr": "Windows bloque explicitement watch2notif sur les réseaux Publics. Autorisez le transfert local pour remplacer ce blocage par une permission limitée."},
    "pair_firewall_failed": {"en": "Windows permission cancelled or unavailable. Check watch2notif in Windows Firewall, then generate a new QR.", "fr": "Autorisation Windows annulée ou indisponible. Vérifiez watch2notif dans le pare-feu Windows, puis générez un nouveau QR."},
    "pair_firewall_cancelled": {"en": "The Windows administrator prompt was cancelled. Generate a new QR before trying again.", "fr": "La demande administrateur Windows a été annulée. Générez un nouveau QR avant de réessayer."},
    "pair_firewall_timeout": {"en": "Windows did not finish configuring the firewall in time. Check its rules before trying again.", "fr": "Windows n'a pas terminé la configuration du pare-feu à temps. Vérifiez ses règles avant de réessayer."},
    "pair_firewall_elevation_failed": {"en": "Windows could not launch the administrator helper. Check your administrator rights and try again.", "fr": "Windows n'a pas pu lancer l'assistant administrateur. Vérifiez vos droits administrateur puis réessayez."},
    "pair_firewall_rules_read_failed": {"en": "The administrator helper could not read the local firewall rules. Check Windows Firewall.", "fr": "L'assistant administrateur n'a pas pu lire les règles locales du pare-feu. Vérifiez le pare-feu Windows."},
    "pair_firewall_rule_create_failed": {"en": "Windows could not create the scoped local-transfer permission. Check Windows Firewall.", "fr": "Windows n'a pas pu créer l'autorisation limitée du transfert local. Vérifiez le pare-feu Windows."},
    "pair_firewall_block_disable_failed": {"en": "Windows could not replace watch2notif's Public TCP block. Check Windows Firewall.", "fr": "Windows n'a pas pu remplacer le blocage TCP Public de watch2notif. Vérifiez le pare-feu Windows."},
    "pair_firewall_verification_failed": {"en": "The effective firewall permission could not be verified. Check Windows Firewall before scanning a new QR.", "fr": "L'autorisation effective du pare-feu n'a pas pu être vérifiée. Vérifiez le pare-feu Windows avant de scanner un nouveau QR."},
    "pair_firewall_rollback_failed": {"en": "Windows could not fully restore the rules after a failure. Check watch2notif's firewall rules before trying again.", "fr": "Windows n'a pas pu rétablir toutes les règles après un échec. Vérifiez les règles du pare-feu pour watch2notif avant de réessayer."},
    "pair_used": {"en": "Encrypted configuration retrieved. Access is closed.", "fr": "Configuration chiffrée récupérée. Accès fermé."},
    "pair_connection_received": {"en": "A local connection reached the PC.", "fr": "Une connexion locale a atteint le PC."},
    "pair_no_connection": {"en": "No local connection reached the PC. Check the shared Wi-Fi and PC firewall.", "fr": "Aucune connexion locale n'a atteint le PC. Vérifiez le Wi-Fi commun et le pare-feu du PC."},
    "pair_write_failed": {"en": "The encrypted response could not be sent completely. Access is closed; generate a new QR.", "fr": "La réponse chiffrée n'a pas pu être envoyée entièrement. L'accès est fermé ; générez un nouveau QR."},
    "pair_expired": {"en": "QR expired. Access is closed. Generate a new QR to try again.", "fr": "QR expiré. Accès fermé. Générez un nouveau QR pour réessayer."},
    "pair_unavailable": {
        "en": "Local transfer unavailable. Check the network, installed dependencies and PC firewall.",
        "fr": "Transfert local indisponible. Vérifiez le réseau, les dépendances installées et le pare-feu du PC.",
    },
    "pair_close_button": {"en": "Close access", "fr": "Fermer l'accès"},
    "autostart_error_title": {"en": "Autostart error", "fr": "Erreur de démarrage automatique"},
    "ok_title": {"en": "OK", "fr": "OK"},
    "ok_msg": {"en": "Settings saved to config.json.", "fr": "Réglages sauvegardés dans config.json."},
    "save_failed": {"en": "Settings could not be saved. Is watch2notif still running?",
                    "fr": "Réglages non sauvegardés. watch2notif tourne-t-il toujours ?"},
    # Le menu de l'icone vient, traduit, de nico579_commons.tray. Ces cles
    # tray_* gardent leur nom d'origine mais servent la page : case de
    # pause et bandeau de mise a jour.
    "tray_pause": {"en": "Pause polling", "fr": "Mettre en pause"},
    "help_link": {"en": "Help (GitHub)", "fr": "Aide (GitHub)"},
    "update_notif_title": {"en": "watch2notif update available", "fr": "Mise à jour de watch2notif disponible"},
    "update_notif_body": {
        "en": "Version {version} is out (currently running {current}). Open the tray menu to install it.",
        "fr": "La version {version} est sortie (version actuelle : {current}). Ouvrez le menu de l'icône watch2notif pour l'installer.",
    },
    "history_window_title": {
        "en": "watch2notif - notification history",
        "fr": "watch2notif - historique des notifications",
    },
    "history_hint_text": {
        "en": "Click a title to open its link, × to remove a line from the history.",
        "fr": "Cliquez sur un titre pour ouvrir son lien, sur × pour retirer une ligne de l'historique.",
    },
    "history_delete_title": {
        "en": "Remove this line from the history",
        "fr": "Retirer cette ligne de l'historique",
    },
    "history_header_date": {"en": "Date", "fr": "Date"},
    "history_header_source": {"en": "Source", "fr": "Source"},
    "history_header_title": {"en": "Notification", "fr": "Notification"},
    "history_clear_button": {"en": "Clear history", "fr": "Vider l'historique"},
    "history_close_button": {"en": "Close", "fr": "Fermer"},
}


@functools.lru_cache(maxsize=1)
def detect_default_lang() -> str:
    """"fr" si la langue du systeme est le francais, "en" sinon. Mise en cache :
    elle ne change pas en cours de route, et sous macOS elle coute un appel a
    `defaults`."""
    try:
        return "fr" if _langue_systeme() == "fr" else "en"
    except Exception:
        return "en"


# Remplace locale.getdefaultlocale(), deprecie depuis Python 3.11 et retire en
# 3.15. locale.getlocale(), son successeur, lit la locale que Python configure
# au demarrage, ce que l'executable PyInstaller ne fait pas forcement : rien
# ici n'en depend.
def _langue_systeme(plateforme: str | None = None, environ=None) -> str:
    """Code de langue en minuscules ("fr", "en"...), ou "" si rien ne le dit."""
    plateforme = plateforme or sys.platform
    environ = os.environ if environ is None else environ
    if plateforme == "win32":
        import ctypes
        # Langue d'affichage de Windows, pas son format regional. Les 10 bits
        # bas du LANGID sont la langue principale (PRIMARYLANGID) : 0x0C est
        # LANG_FRENCH, quel que soit le pays.
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "fr" if langid & 0x3FF == 0x0C else ""
    # L'ordre dans lequel gettext cherche la langue des messages.
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        code = _code_langue(environ.get(variable, "").split(":")[0])
        if code:
            return code
    if plateforme == "darwin":
        # Une application lancee du Finder ou par launchd n'a pas LANG : la
        # langue choisie dans les Reglages Systeme est la preference AppleLanguages.
        sortie = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                                capture_output=True, text=True, timeout=5, check=False).stdout
        return _code_langue(_premiere_langue_apple(sortie))
    return ""


def _code_langue(valeur: str) -> str:
    """"fr" pour fr_FR.UTF-8, fr-CA ou fr ; "" pour C, POSIX ou une chaine vide."""
    code = re.split(r"[_.@-]", valeur.strip(), maxsplit=1)[0].lower()
    return "" if code in ("", "c", "posix") else code


def _premiere_langue_apple(sortie: str) -> str:
    """Premier element de `defaults read -g AppleLanguages`, une liste au format
    plist texte : "(\\n    \\"fr-FR\\",\\n    en\\n)" donne "fr-FR"."""
    for element in sortie.strip().strip("()").split(","):
        element = element.strip().strip('"')
        if element:
            return element
    return ""


def t(key: str, lang: str, **kwargs) -> str:
    text = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    return text.format(**kwargs) if kwargs else text
