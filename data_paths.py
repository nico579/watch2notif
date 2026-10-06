"""Separe le dossier d'installation (le programme) du dossier de donnees
(config/etat/historique de l'utilisateur).

INSTALL_DIR est a cote de l'executable fige (sys.executable) ou du script
en mode source (__file__) : PyInstaller le recree entierement a chaque
build (--clean) et self_update.py le remplace a chaque mise a jour. Jamais
un bon endroit pour des donnees a garder.

DATA_DIR est le dossier standard fourni par la plateforme pour les
donnees d'un utilisateur (%APPDATA% sous Windows, XDG_DATA_HOME sous
Linux, Application Support sous Mac, via platformdirs) : aucune
reinstallation, mise a jour ou reconstruction ne le touche. Meme regle que
blink2video, lidar2map et gpxsolar : WATCH2NOTIF_HOME l'emporte (tests,
installation particuliere).

Avant ce module, config.json/state/ etc. vivaient directement dans
INSTALL_DIR, qui faisait donc double emploi : un `python build.py` local
lance le 2026-09-17 a efface la configuration reelle de Nico (18 sources)
et l'historique de dedup avec le reste du dossier reconstruit.

Toute la logique (calcul du dossier, reprise unique des donnees d'une
installation anterieure) est dans nico579_commons.dossiers, la meme pour les
quatre applications. Ce qui reste ici est propre a watch2notif : ses noms, ses
fichiers et son dossier d'installation. notifier.main() appelle
DOSSIERS.preparer_etat(INSTALL_DIR) au demarrage.
"""
import sys
from pathlib import Path

from nico579_commons.dossiers import Dossiers

INSTALL_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent

DOSSIERS = Dossiers(
    "watch2notif",
    # Le dossier d'etat s'appelle « watch2notif », pas « watch2notif-data » :
    # les donnees des utilisateurs y sont deja.
    nom_etat="watch2notif",
    nom_sorties="watch2notif",
    variable_home="WATCH2NOTIF_HOME",
    # Noms herites de l'epoque ou INSTALL_DIR faisait aussi office de DATA_DIR.
    # watch2notif.log volontairement absent : en mode fige, notifier.py cree son
    # log a l'import (avant meme la reprise) si sys.stdout est None, donc la
    # cible existe toujours - un vieux log n'est que du texte de diagnostic,
    # pas une donnee a proteger comme les autres.
    fichiers_etat=("config.json", "notification_history.json", ".watch2notif.lock", "state"),
    marqueur=".watch2notif_etat_migre.json",
)
DATA_DIR = DOSSIERS.dossier_etat()
# Cree tout de suite, a l'import : notifier.py ouvre son fichier de log
# dans DATA_DIR avant meme d'appeler DOSSIERS.preparer_etat() (le tout
# premier print() possible, avant que main() ne tourne).
DATA_DIR.mkdir(parents=True, exist_ok=True)
