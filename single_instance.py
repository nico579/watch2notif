"""Empeche de lancer deux pollers en meme temps (autostart + lancement
manuel, ou double-clic accidentel) : verrou de fichier au niveau OS,
libere automatiquement par le systeme quand le process se termine, meme
sur crash. Pas de fichier PID a nettoyer ni de risque qu'un PID recycle
plus tard par un autre process fasse croire qu'une instance tourne
encore (piege classique des schemas a fichier PID) : le verrou EST l'etat,
il n'y a rien a interpreter.
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# Garde le handle ouvert pour la duree de vie du process : le verrou tient
# tant qu'il l'est, se relache tout seul (fermeture du fd) a la sortie.
_lock_file = None


def acquire(base_dir: Path) -> bool:
    """Vrai si le verrou a ete pris (aucune autre instance active)."""
    global _lock_file
    lock_path = base_dir / ".watch2notif.lock"

    lock_path.touch(exist_ok=True)
    if lock_path.stat().st_size == 0:
        lock_path.write_bytes(b"0")

    handle = open(lock_path, "r+b")
    try:
        if sys.platform == "win32":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    _lock_file = handle  # reference gardee : fermer le fd liberait le verrou
    return True
