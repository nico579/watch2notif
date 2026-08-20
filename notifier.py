"""Poll the sources enabled in config.json (RSS/Atom feeds, GitHub issues,
see providers/) and fire a desktop notification for anything new.
Cross-platform (Windows/Linux/Mac). Settings (which sources, intervals)
are edited via settings.py.
"""
import json
import sys
import time
from pathlib import Path

import notify_backend
from providers import DEFAULT_KIND, PROVIDERS

# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# (sys._MEIPASS) une fois fige, pas vers le dossier de l'executable : c'est
# la aussi qu'il faut config.json/state/, a cote du .exe reel.
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent

CONFIG_FILE = BASE_DIR / "config.json"
STATE_DIR = BASE_DIR / "state"

# En executable "windowed" (console=False, cf watch2notif.spec), Windows ne
# donne pas de console au process : sys.stdout/stderr valent None, et le
# moindre print() plante. On redirige alors vers un fichier de log a cote
# de l'executable, seul moyen de garder une trace d'un poller silencieux.
if sys.stdout is None:
    log_file = open(BASE_DIR / "watch2notif.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log_file
else:
    sys.stdout.reconfigure(line_buffering=True)


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def state_file(feed_key: str) -> Path:
    return STATE_DIR / f"{feed_key}.json"


def load_seen_ids(feed_key: str) -> set[str]:
    path = state_file(feed_key)
    if path.exists():
        return set(json.loads(path.read_text(encoding="utf-8")))
    return set()


def save_seen_ids(feed_key: str, seen_ids: set[str]) -> None:
    state_file(feed_key).write_text(json.dumps(sorted(seen_ids)), encoding="utf-8")


def fetch_entries(feed: dict):
    provider = PROVIDERS[feed.get("kind", DEFAULT_KIND)]
    return provider.fetch_entries(feed["url"])


TITLE_MAX_LEN = 100


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def notify(feed_label: str, entry) -> None:
    title = entry.get("title", "(sans titre)")
    author = entry.get("author", "?")
    body = (entry.get("summary") or "").strip().replace("\n", " ")
    if len(body) > 150:
        body = body[:150] + "..."
    full_title = f"[{feed_label}] {title}"
    notify_backend.notify(
        title=_truncate(full_title, TITLE_MAX_LEN),
        message=f"{author} - {body}" if body else author,
        url=entry.get("link", ""),
    )


def poll_feed(feed: dict) -> None:
    key, label = feed["key"], feed["label"]
    first_run = not state_file(key).exists()
    seen_ids = load_seen_ids(key)

    entries = fetch_entries(feed)

    if first_run:
        seen_ids.update(e.id for e in entries)
        save_seen_ids(key, seen_ids)
        print(f"[{label}] premier lancement: {len(entries)} item(s) amorces, aucune notif.")
        return

    new_entries = [e for e in entries if e.id not in seen_ids]
    for entry in reversed(new_entries):
        notify(label, entry)
        seen_ids.add(entry.id)
    if new_entries:
        save_seen_ids(key, seen_ids)
        print(f"[{label}] {len(new_entries)} nouvelle(s) notif(s) envoyee(s).")


def main() -> None:
    if not CONFIG_FILE.exists():
        sys.exit("config.json manquant. Lance settings.py pour le creer.")

    STATE_DIR.mkdir(exist_ok=True)
    print("watch2notif demarre. Ctrl+C pour arreter.")

    next_due: dict = {}

    while True:
        config = load_config()
        default_interval = config.get("poll_interval_seconds", 60)
        active_feeds = [f for f in config["feeds"] if f["enabled"] and f["url"]]

        if not active_feeds:
            print("aucune source active dans config.json (lance settings.py).")

        now = time.time()
        for feed in active_feeds:
            key = feed["key"]
            if now < next_due.get(key, 0):
                continue
            interval = feed.get("interval_seconds") or default_interval
            try:
                poll_feed(feed)
            except Exception as exc:
                print(f"[{feed['label']}] erreur, on reessaie au prochain cycle: {exc}")
            next_due[key] = now + interval

        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\narret demande, bye.")
