"""Persisted trail of desktop notifications actually sent, for the tray's
history window. Distinct from providers/state/ (which only keeps seen IDs
and a watermark to dedupe future polls, never the content): this is a
bounded, human-readable log meant to be read back and displayed."""
import threading
import time

import data_paths
import json_store

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
        data = json_store.read_json(HISTORY_FILE, [])
    except OSError:
        return []
    return data if isinstance(data, list) else []


def _save(entries: list) -> None:
    json_store.write_json_atomic(HISTORY_FILE, entries, indent=2)


def append(feed_label: str, title: str, author: str, summary: str, link: str) -> None:
    """Ajoute une entree ; ne leve jamais : appele par notify() APRES le
    toast, une exception ici remonterait dans le poll alors que la
    notification est deja partie."""
    with _lock:
        try:
            # read_json, pas load() : un historique present mais illisible
            # (refus Windows qui persiste) leve au lieu de rendre [], sinon
            # la reecriture ci-dessous l'effacait en ne gardant que cette
            # entree (constate le 2026-09-24).
            entries = json_store.read_json(HISTORY_FILE, [])
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
