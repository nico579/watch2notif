"""Persisted trail of desktop notifications actually sent, for the tray's
history window. Distinct from providers/state/ (which only keeps seen IDs
and a watermark to dedupe future polls, never the content): this is a
bounded, human-readable log meant to be read back and displayed."""
import json
import os
import threading
import time

import data_paths

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
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(entries: list) -> None:
    tmp = HISTORY_FILE.with_suffix(HISTORY_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)


def append(feed_label: str, title: str, author: str, summary: str, link: str) -> None:
    with _lock:
        entries = load()
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


def clear() -> None:
    with _lock:
        _save([])
