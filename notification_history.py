"""Persisted trail of desktop notifications actually sent, for the tray's
history window. Distinct from providers/state/ (which only keeps seen IDs
and a watermark to dedupe future polls, never the content): this is a
bounded, human-readable log meant to be read back and displayed."""
import json
import os
import time

import data_paths

HISTORY_FILE = data_paths.DATA_DIR / "notification_history.json"
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
