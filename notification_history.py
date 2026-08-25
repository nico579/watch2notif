"""Persisted trail of desktop notifications actually sent, for the tray's
history window. Distinct from providers/state/ (which only keeps seen IDs
and a watermark to dedupe future polls, never the content): this is a
bounded, human-readable log meant to be read back and displayed."""
import json
import os
import sys
import time
from pathlib import Path

# Meme resolution que BASE_DIR dans notifier.py/settings.py : __file__ pointe
# vers le dossier d'extraction temporaire de PyInstaller une fois fige, pas
# vers le dossier de l'executable.
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
HISTORY_FILE = BASE_DIR / "notification_history.json"
MAX_ENTRIES = 200


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
    _save([])
