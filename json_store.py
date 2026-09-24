"""Lecture/ecriture des fichiers JSON de donnees (config, etats, historique).

watch2notif fait tourner dans un meme processus le serveur HTTP (un thread
par requete), la boucle de poll et d'autres threads, qui lisent et
ecrivent les memes fichiers. Trois pieges, tous constates le 2026-09-24 :

- un temporaire au nom fixe (``config.json.tmp``) partage par deux
  ecrivains simultanes : le second ``os.replace`` trouve le temporaire deja
  consomme (FileNotFoundError, reproduit dans blink2video, meme schema) ;
- sous Windows, remplacer un fichier qu'un autre thread lit, ou lire un
  fichier en cours de remplacement, echoue en PermissionError ;
- rendre un defaut sur une lecture ratee, puis reecrire : l'historique etait
  alors reduit a la seule entree ajoutee.

D'ou : un verrou par fichier partage par lecteurs ET ecrivains (un seul
processus, cf. single_instance.py), un temporaire unique par ecriture, et
quelques nouvelles tentatives sur refus passager (antivirus, indexeur),
comme pip autour d'os.replace.
"""
import json
import os
import threading
import time
import uuid
from pathlib import Path

_TENTATIVES = 10
_PAUSE_S = 0.05

_verrous: dict = {}
_verrou_des_verrous = threading.Lock()


def file_lock(path: Path) -> threading.Lock:
    """Verrou propre a ``path`` pour les threads de ce processus."""
    with _verrou_des_verrous:
        return _verrous.setdefault(os.path.abspath(path), threading.Lock())


def read_json(path: Path, default, *, tolerate_corrupt: bool = True):
    """Contenu JSON de ``path``, ``default`` s'il est absent.

    Un fichier present mais illisible (refus qui persiste, erreur disque)
    leve l'OSError au lieu de rendre ``default`` : un appelant qui reecrit
    ensuite effacerait sinon tout le contenu. JSON invalide : ``default``
    si ``tolerate_corrupt``, sinon l'erreur remonte (config.json : un
    fichier corrompu peut encore se reparer a la main, il ne doit pas etre
    remplace en silence par la config par defaut)."""
    path = Path(path)
    with file_lock(path):
        for tentative in range(_TENTATIVES):
            try:
                texte = path.read_text(encoding="utf-8")
                break
            except FileNotFoundError:
                return default
            except PermissionError:
                if tentative == _TENTATIVES - 1:
                    raise
                time.sleep(_PAUSE_S)
    try:
        return json.loads(texte)
    except ValueError:
        if tolerate_corrupt:
            return default
        raise


def write_json_atomic(path: Path, data, indent=None) -> None:
    """Remplace ``path`` d'un bloc : un lecteur voit l'ancien ou le nouveau
    contenu, jamais un fichier tronque."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    contenu = json.dumps(data, indent=indent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    with file_lock(path):
        try:
            tmp.write_text(contenu, encoding="utf-8")
            for tentative in range(_TENTATIVES):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if tentative == _TENTATIVES - 1:
                        raise
                    time.sleep(_PAUSE_S)
        finally:
            tmp.unlink(missing_ok=True)
