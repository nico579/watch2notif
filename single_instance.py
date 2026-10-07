"""Empeche de lancer deux pollers en meme temps (autostart + lancement
manuel, ou double-clic accidentel) : verrou de fichier au niveau OS,
libere automatiquement par le systeme quand le process se termine, meme
sur crash. Pas de fichier PID a nettoyer ni de risque qu'un PID recycle
plus tard par un autre process fasse croire qu'une instance tourne
encore (piege classique des schemas a fichier PID) : le verrou EST l'etat,
il n'y a rien a interpreter.

Le verrou est celui de nico579_commons.atomique, le meme que pour les
fichiers d'etat des autres applications. Il porte le meme fichier
(.watch2notif.lock) et le meme octet qu'avant : une version plus ancienne
encore en cours d'execution (la mise a jour lance la nouvelle avant la sortie
de l'ancienne) reste exclue par la nouvelle, et inversement.
"""
import contextlib
from pathlib import Path

from nico579_commons import atomique

# Tient le verrou pour la duree de vie du process : le contexte reste ouvert
# tant qu'on ne le ferme pas, et l'OS le rend de toute facon a la sortie.
_verrou = None


def acquire(base_dir: Path) -> bool:
    """Vrai si le verrou a ete pris (aucune autre instance active)."""
    global _verrou
    pile = contextlib.ExitStack()
    try:
        # « .lock » est ajoute par atomique : le fichier est .watch2notif.lock.
        pile.enter_context(atomique.verrou_inter_processus(
            Path(base_dir) / ".watch2notif", delai_s=0))
    except (TimeoutError, OSError):
        return False
    _verrou = pile
    return True


def release() -> None:
    """Relache le verrou avant la fin du process : Redemarrer lance le
    nouveau process avant que celui-ci ne soit sorti, et le nouveau doit
    pouvoir le prendre."""
    global _verrou
    if _verrou is None:
        return
    _verrou.close()
    _verrou = None
