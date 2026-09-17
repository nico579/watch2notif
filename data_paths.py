"""Separe le dossier d'installation (le programme) du dossier de donnees
(config/etat/historique de l'utilisateur).

INSTALL_DIR est a cote de l'executable fige (sys.executable) ou du script
en mode source (__file__) : PyInstaller le recree entierement a chaque
build (--clean) et self_update.py le remplace a chaque mise a jour. Jamais
un bon endroit pour des donnees a garder.

DATA_DIR est le dossier standard fourni par la plateforme pour les
donnees d'un utilisateur (%APPDATA% sous Windows, XDG_DATA_HOME sous
Linux, Application Support sous Mac, via platformdirs) : aucune
reinstallation, mise a jour ou reconstruction ne le touche.

Avant ce module, config.json/state/ etc. vivaient directement dans
INSTALL_DIR, qui faisait donc double emploi : un `python build.py` local
lance le 2026-09-17 a efface la configuration reelle de Nico (18 sources)
et l'historique de dedup avec le reste du dossier reconstruit.
migrer_donnees_existantes() deplace une bonne fois les fichiers d'une
installation anterieure a ce module vers DATA_DIR.
"""
import shutil
import sys
from pathlib import Path

from platformdirs import user_data_dir

INSTALL_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DATA_DIR = Path(user_data_dir("watch2notif", appauthor=False))
# Cree tout de suite, a l'import : notifier.py ouvre son fichier de log
# dans DATA_DIR avant meme d'appeler migrer_donnees_existantes() (le tout
# premier print() possible, avant que main() ne tourne).
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Noms herites de l'epoque ou INSTALL_DIR faisait aussi office de DATA_DIR.
# watch2notif.log volontairement absent : en mode fige, notifier.py cree son
# log a l'import (avant meme cet appel) si sys.stdout est None, donc la
# cible existe toujours avant que la migration ne l'atteigne - un vieux log
# n'est que du texte de diagnostic, pas une donnee a proteger comme les
# trois autres.
_FICHIERS_HERITES = ("config.json", "notification_history.json", ".watch2notif.lock")
_DOSSIERS_HERITES = ("state",)


def migrer_donnees_existantes() -> None:
    """Deplace les donnees d'une installation anterieure a DATA_DIR, une
    seule fois (marqueur pose a la fin). Ne fait rien pour une installation
    neuve (rien a migrer) ni pour un second appel (deja migre)."""
    marqueur = DATA_DIR / ".migrated_from_install_dir"
    if marqueur.exists():
        return

    for nom in _FICHIERS_HERITES:
        source = INSTALL_DIR / nom
        cible = DATA_DIR / nom
        if source.exists() and not cible.exists():
            shutil.move(str(source), str(cible))
    for nom in _DOSSIERS_HERITES:
        source = INSTALL_DIR / nom
        cible = DATA_DIR / nom
        if source.is_dir() and not cible.exists():
            shutil.move(str(source), str(cible))
    marqueur.touch()
