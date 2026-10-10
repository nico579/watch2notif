"""Persisted trail of desktop notifications actually sent, for the tray's
history window. Distinct from providers/state/ (which only keeps seen IDs
and a watermark to dedupe future polls, never the content): this is a
bounded, human-readable log meant to be read back and displayed."""
import threading
import time

import data_paths
from nico579_commons import atomique

HISTORY_FILE = data_paths.DATA_DIR / "notification_history.json"
MAX_ENTRIES = 200

# append() tourne sur le thread de poll, clear() sur le thread HTTP (route
# /api/clear-history) : sans ce verrou, un append() qui avait lu l'ancien
# etat juste avant un clear() concurrent le reecrit juste apres, faisant
# reapparaitre les entrees qu'on venait de vider (trouve en audit, race
# etroite mais reproduite de facon deterministe : lecture avant clear,
# ecriture apres).
_lock = threading.Lock()


def load() -> list:
    """Historique pour l'affichage : liste vide si absent, corrompu ou
    illisible. Rien n'est reecrit a partir d'ici (cf. append)."""
    try:
        data = atomique.lire_json(HISTORY_FILE, [])
    except OSError:
        return []
    return data if isinstance(data, list) else []


def _save(entries: list) -> None:
    atomique.ecrire_json(HISTORY_FILE, entries, indent=2)


def append(feed_label: str, title: str, author: str, summary: str, link: str) -> None:
    """Ajoute une entree ; ne leve jamais : appele par notify() APRES le
    toast, une exception ici remonterait dans le poll alors que la
    notification est deja partie."""
    with _lock:
        try:
            # lire_json, pas load() : un historique present mais illisible
            # (refus Windows qui persiste) leve au lieu de rendre [], sinon
            # la reecriture ci-dessous l'effacait en ne gardant que cette
            # entree (constate le 2026-09-24).
            entries = atomique.lire_json(HISTORY_FILE, [])
            if not isinstance(entries, list):
                entries = []
            entries.insert(0, {
                "feed_label": feed_label,
                "title": title,
                "author": author,
                "summary": summary,
                "link": link,
                "timestamp": time.time(),
            })
            del entries[MAX_ENTRIES:]
            _save(entries)
        except OSError as exc:
            print(f"historique non mis a jour ({exc}), entree ignoree")


def clear() -> None:
    with _lock:
        _save([])


def remove(timestamp, link: str) -> bool:
    """Retire une ligne de l'historique. Vrai si elle y etait.

    La ligne est reperee par son horodatage et son lien, pas par sa position :
    le poll peut avoir insere une nouvelle notification en tete entre
    l'affichage de la page et le clic, ce qui decalerait tous les rangs. Une
    seule ligne part, meme si deux partagent le meme lien (une notification
    renvoyee). Meme verrou que append() et clear()."""
    try:
        cible = float(timestamp)
    except (TypeError, ValueError):
        return False
    with _lock:
        entries = atomique.lire_json(HISTORY_FILE, [])
        if not isinstance(entries, list):
            return False
        for index, ligne in enumerate(entries):
            if (isinstance(ligne, dict) and ligne.get("link", "") == (link or "")
                    and isinstance(ligne.get("timestamp"), (int, float))
                    and abs(ligne["timestamp"] - cible) < 1e-6):
                del entries[index]
                _save(entries)
                return True
    return False
