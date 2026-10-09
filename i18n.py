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
        "fr": "Ne notifier que les entrees qu'un modele d'IA juge conformes a votre consigne "
              "(demande ANTHROPIC_API_KEY, voir README)",
    },
    "filter_key_missing": {
        "en": "No ANTHROPIC_API_KEY on this computer: this filter will not sort anything, "
              "every entry is notified. How to get one and set it:",
        "fr": "Pas de cle ANTHROPIC_API_KEY sur cet ordinateur : ce filtre ne triera rien, "
              "toutes les entrees seront notifiees. Comment l'obtenir et la poser :",
    },
    "filter_key_url": {
        "en": "https://github.com/nico579/watch2notif#ai-filter-optional",
        "fr": "https://github.com/nico579/watch2notif/blob/master/README.fr.md#filtre-ia-facultatif",
    },
    "filter_placeholder": {
        "en": "Instructions for the AI filter: which entries deserve a notification? "
              "Empty = notify everything.",
        "fr": "Consigne du filtre IA : quelles entrees meritent une notification ? "
              "Vide = tout notifier.",
    },
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
    "config_import_button": {"en": "Import JSON", "fr": "Importer un JSON"},
    "config_export_button": {"en": "Export JSON", "fr": "Exporter un JSON"},
    "config_transfer_note": {
        "en": "Share source settings with Android using a JSON file. Claude rules are preserved. API keys, history and system settings stay on each device. Feed URLs can contain private tokens: keep the file private.",
        "fr": "Transferez les sources vers Android avec un fichier JSON. Les consignes Claude sont conservees. Les cles API, l'historique et les reglages systeme restent sur chaque appareil. Les URLs de flux peuvent contenir des tokens prives : gardez le fichier prive.",
    },
    "config_import_confirm": {
        "en": "Replace the sources displayed here with {count} imported sources? Click Save afterwards to apply them.",
        "fr": "Remplacer les sources affichees par les {count} sources importees ? Cliquez ensuite sur Sauvegarder pour les appliquer.",
    },
    "config_imported": {"en": "Sources imported. Click Save to apply them.", "fr": "Sources importees. Cliquez sur Sauvegarder pour les appliquer."},
    "config_exported": {"en": "Configuration exported.", "fr": "Configuration exportee."},
    "config_invalid": {"en": "Invalid configuration. No settings changed.", "fr": "Configuration invalide. Aucun reglage modifie."},
    "pair_send_button": {"en": "Send to phone", "fr": "Envoyer vers le telephone"},
    "pair_title": {"en": "Pair your phone", "fr": "Appairer le telephone"},
    "pair_note": {
        "en": "Connect both devices to the same local network. In Android Settings, tap Scan the PC QR. Sources, Claude rules and API keys are encrypted; the decryption key is only in this QR. Treat the QR as private.",
        "fr": "Connectez les deux appareils au meme reseau local. Dans les Reglages Android, touchez Scanner le QR du PC. Les sources, consignes Claude et cles API sont chiffrees ; la cle de dechiffrement est uniquement dans ce QR. Gardez ce QR prive.",
    },
    "pair_ready": {"en": "PC: {address} - expires in {seconds} s", "fr": "PC : {address} - expire dans {seconds} s"},
    "pair_address_label": {"en": "PC network connected to the phone", "fr": "Reseau du PC relie au telephone"},
    "pair_preparing": {"en": "Preparing local access…", "fr": "Preparation de l'acces local…"},
    "pair_public_network": {
        "en": "Windows marks this network as Public. Its firewall may block the phone. Use Allow local transfer below if needed.",
        "fr": "Windows classe ce reseau comme Public. Son pare-feu peut bloquer le telephone. Utilisez Autoriser le transfert local ci-dessous si necessaire.",
    },
    "pair_allow_button": {"en": "Allow local transfer", "fr": "Autoriser le transfert local"},
    "pair_renew_button": {"en": "Generate a new QR", "fr": "Generer un nouveau QR"},
    "pair_firewall_note": {
        "en": "This button requests Windows administrator consent. It replaces watch2notif's general TCP block on Public networks with a permission limited to this app, the selected PC address and local-subnet peers. The rule remains saved; the encrypted transfer port closes after use or 2 minutes.",
        "fr": "Ce bouton demande le consentement administrateur Windows. Il remplace le blocage TCP general de watch2notif sur les reseaux Publics par une autorisation limitee a cette application, a l'adresse PC choisie et au sous-reseau local. La regle reste enregistree ; le port du transfert chiffre se ferme apres usage ou 2 minutes.",
    },
    "pair_firewall_wait": {"en": "Accept the Windows administrator prompt…", "fr": "Validez la demande administrateur de Windows…"},
    "pair_firewall_allowed": {"en": "Local transfer allowed. Scan the new QR. Phone connectivity still needs to be checked.", "fr": "Transfert local autorise. Scannez le nouveau QR. La connexion du telephone reste a verifier."},
    "pair_firewall_blocked": {
        "en": "A firewall block rule takes priority and cannot be replaced by this button. Check watch2notif in Windows Firewall.",
        "fr": "Une regle de blocage du pare-feu est prioritaire et ne peut pas etre remplacee par ce bouton. Verifiez watch2notif dans le pare-feu Windows.",
    },
    "pair_firewall_detected": {"en": "Windows explicitly blocks watch2notif on Public networks. Allow local transfer to replace this block with a scoped permission.", "fr": "Windows bloque explicitement watch2notif sur les reseaux Publics. Autorisez le transfert local pour remplacer ce blocage par une permission limitee."},
    "pair_firewall_failed": {"en": "Windows permission cancelled or unavailable. Check watch2notif in Windows Firewall, then generate a new QR.", "fr": "Autorisation Windows annulee ou indisponible. Verifiez watch2notif dans le pare-feu Windows, puis generez un nouveau QR."},
    "pair_firewall_cancelled": {"en": "The Windows administrator prompt was cancelled. Generate a new QR before trying again.", "fr": "La demande administrateur Windows a ete annulee. Generez un nouveau QR avant de reessayer."},
    "pair_firewall_timeout": {"en": "Windows did not finish configuring the firewall in time. Check its rules before trying again.", "fr": "Windows n'a pas termine la configuration du pare-feu a temps. Verifiez ses regles avant de reessayer."},
    "pair_firewall_elevation_failed": {"en": "Windows could not launch the administrator helper. Check your administrator rights and try again.", "fr": "Windows n'a pas pu lancer l'assistant administrateur. Verifiez vos droits administrateur puis reessayez."},
    "pair_firewall_rules_read_failed": {"en": "The administrator helper could not read the local firewall rules. Check Windows Firewall.", "fr": "L'assistant administrateur n'a pas pu lire les regles locales du pare-feu. Verifiez le pare-feu Windows."},
    "pair_firewall_rule_create_failed": {"en": "Windows could not create the scoped local-transfer permission. Check Windows Firewall.", "fr": "Windows n'a pas pu creer l'autorisation limitee du transfert local. Verifiez le pare-feu Windows."},
    "pair_firewall_block_disable_failed": {"en": "Windows could not replace watch2notif's Public TCP block. Check Windows Firewall.", "fr": "Windows n'a pas pu remplacer le blocage TCP Public de watch2notif. Verifiez le pare-feu Windows."},
    "pair_firewall_verification_failed": {"en": "The effective firewall permission could not be verified. Check Windows Firewall before scanning a new QR.", "fr": "L'autorisation effective du pare-feu n'a pas pu etre verifiee. Verifiez le pare-feu Windows avant de scanner un nouveau QR."},
    "pair_firewall_rollback_failed": {"en": "Windows could not fully restore the rules after a failure. Check watch2notif's firewall rules before trying again.", "fr": "Windows n'a pas pu retablir toutes les regles apres un echec. Verifiez les regles du pare-feu pour watch2notif avant de reessayer."},
    "pair_used": {"en": "Encrypted configuration retrieved. Access is closed.", "fr": "Configuration chiffree recuperee. Acces ferme."},
    "pair_connection_received": {"en": "A local connection reached the PC.", "fr": "Une connexion locale a atteint le PC."},
    "pair_no_connection": {"en": "No local connection reached the PC. Check the shared Wi-Fi and PC firewall.", "fr": "Aucune connexion locale n'a atteint le PC. Verifiez le Wi-Fi commun et le pare-feu du PC."},
    "pair_write_failed": {"en": "The encrypted response could not be sent completely. Access is closed; generate a new QR.", "fr": "La reponse chiffree n'a pas pu etre envoyee entierement. L'acces est ferme ; generez un nouveau QR."},
    "pair_expired": {"en": "QR expired. Access is closed. Generate a new QR to try again.", "fr": "QR expire. Acces ferme. Generez un nouveau QR pour reessayer."},
    "pair_unavailable": {
        "en": "Local transfer unavailable. Check the network, installed dependencies and PC firewall.",
        "fr": "Transfert local indisponible. Verifiez le reseau, les dependances installees et le pare-feu du PC.",
    },
    "pair_close_button": {"en": "Close access", "fr": "Fermer l'acces"},
    "autostart_error_title": {"en": "Autostart error", "fr": "Erreur autostart"},
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
