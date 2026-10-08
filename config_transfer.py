"""Portable source settings for desktop / Android import and export.

Credentials, paths, autostart, pause, history and deduplication state stay local.
"""
import re
import uuid
from urllib.parse import urlparse

KINDS = {"rss", "github_issues", "github_discussion", "github_sponsors", "youtube_comments"}
MAX_SOURCES = 50


def portable_config(config: dict) -> dict:
    if not isinstance(config, dict) or not isinstance(config.get("feeds"), list):
        raise ValueError("invalid configuration")
    rows = config["feeds"]
    if len(rows) > 200:
        raise ValueError("too many sources")
    feeds, keys = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid source")
        address = str(row.get("url") or "").strip()
        if not address:
            continue
        kind = row.get("kind", "rss")
        label = str(row.get("label") or address).strip()
        instruction = str(row.get("filtre_ia") or "").strip()
        if kind not in KINDS or len(address) > 8192 or not label or len(label) > 200 or len(instruction) > 4000:
            raise ValueError("invalid source")
        default = 60 if kind == "rss" else 1800 if kind == "github_sponsors" else 300
        interval = row.get("interval_seconds")
        if interval is None:
            interval = default
        if isinstance(interval, bool) or not isinstance(interval, int) or not 5 <= interval <= 604800:
            raise ValueError("invalid interval")
        enabled = row.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("invalid enabled flag")
        if kind == "rss":
            parsed = urlparse(address)
            valid = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname) and parsed.username is None
        elif kind == "github_issues":
            valid = re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", address)
        elif kind == "github_discussion":
            valid = re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]{0,8}", address)
        elif kind == "github_sponsors":
            valid = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", address)
        else:
            parsed = urlparse(address)
            host = (parsed.hostname or "").lower()
            valid = bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", address)) or (
                parsed.scheme.lower() in {"http", "https"} and parsed.username is None
                and (host == "youtu.be" or host in {"youtube.com", "youtube-nocookie.com"}
                     or host.endswith((".youtube.com", ".youtube-nocookie.com")))
                and bool(re.search(r"(?:[?&]v=|youtu\.be/|/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})(?:[?&#/]|$)", address))
            )
        if not valid:
            raise ValueError("invalid source address")
        key = str(row.get("key") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", key) or key in keys:
            key = str(uuid.uuid4())
        keys.add(key)
        feeds.append({"key": key, "label": label, "kind": kind, "url": address,
                      "enabled": enabled, "interval_seconds": interval, "filtre_ia": instruction})
    if len(feeds) > MAX_SOURCES:
        raise ValueError("too many sources")
    return {"poll_interval_seconds": 60, "feeds": feeds}
