"""Active/desactive le lancement automatique de notifier.py au demarrage
de la session, selon l'OS courant (Windows/Linux/Mac). Utilise par la page de
reglages, par la case a cocher "demarrer avec le systeme".

Le mecanisme (raccourci dans le dossier Demarrage sous Windows, service systemd
utilisateur sous Linux, agent launchd sous macOS) est celui de
nico579_commons.demarrage, le meme que blink2video et lidar2map. Ne reste ici
que ce qui est propre a watch2notif : la commande a lancer et son dossier.
"""
import platform
import sys
from pathlib import Path

from nico579_commons import demarrage


def frozen() -> bool:
    """Vrai lorsque le programme tourne depuis un bundle PyInstaller."""
    return bool(getattr(sys, "frozen", False))


# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# une fois fige, pas vers le dossier de l'executable.
PROJECT_DIR = Path(sys.executable if frozen() else __file__).resolve().parent
NOTIFIER_PATH = PROJECT_DIR / "notifier.py"

LINUX_SERVICE_NAME = "watch2notif.service"
MAC_LABEL = "com.nico.watch2notif"


def notifier_command() -> list:
    """Commande a lancer pour demarrer le poller de fond, adaptee selon
    qu'on tourne depuis les sources ou depuis le bundle fige : dans ce
    dernier cas, watch2notif.exe (executable unique, poller + panneau de
    reglage via --settings) se trouve a cote de l'executable courant."""
    if frozen():
        suffix = ".exe" if platform.system() == "Windows" else ""
        binary = Path(sys.executable).parent / f"watch2notif{suffix}"
        return [str(binary)]
    if platform.system() == "Windows":
        return [str(Path(sys.executable).with_name("pythonw.exe")), str(NOTIFIER_PATH)]
    return [sys.executable, str(NOTIFIER_PATH)]


def entree() -> demarrage.Entree:
    """L'entree de demarrage de watch2notif. Le .vbs des versions <= 0.2.3 est
    retire avec elle (VBScript quitte Windows)."""
    return demarrage.Entree(
        "watch2notif", tuple(notifier_command()), PROJECT_DIR,
        "watch2notif (desktop notifications from RSS feeds and other sources)",
        label_macos=MAC_LABEL, apres_session_graphique=True, attente_relance_s=10,
        retire_vbs=True)


def is_enabled() -> bool:
    return demarrage.est_actif(entree())


def enable() -> None:
    demarrage.activer(entree())


def disable() -> None:
    demarrage.desactiver(entree())


def migrer_ancien_demarrage() -> bool:
    """Remplace le .vbs d'une version <= 0.2.3 par le raccourci, sans
    toucher au choix de l'utilisateur : rien si le demarrage automatique
    n'etait pas actif. Vrai si un remplacement a eu lieu."""
    return demarrage.migrer_vbs(entree())
