"""Poll the sources enabled in config.json (RSS/Atom feeds, GitHub issues,
see providers/) and fire a desktop notification for anything new.
Cross-platform (Windows/Linux/Mac). Settings (which sources, intervals)
are edited via settings.py. Runs the polling in a background thread and
a system tray icon (pause/quit) on the main thread.
"""
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

import i18n
import notify_backend
import update_check
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


def poll_loop(pause_event: threading.Event, update_state: dict, lang: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    print("watch2notif demarre.")

    next_due: dict = {}
    notified_version = None

    while True:
        if pause_event.is_set():
            time.sleep(5)
            continue

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

        info = update_check.disponible(BASE_DIR)
        update_state["info"] = info
        if info and info["version"] != notified_version:
            notified_version = info["version"]
            notify_backend.notify(
                title=i18n.t("update_notif_title", lang),
                message=i18n.t("update_notif_body", lang, version=info["version"], current=update_check.VERSION),
                url=info.get("page") or "",
            )
            print(f"nouvelle version disponible: {info['version']}")

        time.sleep(5)


def _build_tray_icon_image() -> Image.Image:
    """Icone dessinee a la volee (pas d'asset .ico dans le repo) : un
    oeil stylise, coherent avec l'idee de "watch"."""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 14, size - 2, size - 14), fill=(30, 144, 255, 255))
    draw.ellipse((size // 2 - 12, 12, size // 2 + 12, size - 12), fill=(255, 255, 255, 255))
    draw.ellipse((size // 2 - 6, 18, size // 2 + 6, size - 18), fill=(30, 30, 30, 255))
    return image


def open_config_file() -> None:
    if platform.system() == "Windows":
        os.startfile(CONFIG_FILE)
    elif platform.system() == "Darwin":
        subprocess.run(["open", str(CONFIG_FILE)], check=False)
    else:
        subprocess.run(["xdg-open", str(CONFIG_FILE)], check=False)


def open_release_page(url: str) -> None:
    if not url:
        return
    if platform.system() == "Windows":
        os.startfile(url)
    elif platform.system() == "Darwin":
        subprocess.run(["open", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


def run_tray(lang: str, pause_event: threading.Event, update_state: dict) -> None:
    def toggle_pause(icon, item):
        if pause_event.is_set():
            pause_event.clear()
        else:
            pause_event.set()

    def on_open_config(icon, item):
        try:
            open_config_file()
        except Exception as exc:
            print(f"impossible d'ouvrir config.json: {exc}")

    def on_open_release(icon, item):
        info = update_state.get("info") or {}
        try:
            open_release_page(info.get("page"))
        except Exception as exc:
            print(f"impossible d'ouvrir la page de release: {exc}")

    def on_quit(icon, item):
        icon.stop()

    def menu_items():
        yield pystray.MenuItem(i18n.t("tray_pause", lang), toggle_pause, checked=lambda item: pause_event.is_set())
        yield pystray.MenuItem(i18n.t("tray_open_config", lang), on_open_config)
        info = update_state.get("info")
        if info:
            yield pystray.MenuItem(i18n.t("tray_update_available", lang, version=info["version"]), on_open_release)
        yield pystray.MenuItem(i18n.t("tray_quit", lang), on_quit)

    icon = pystray.Icon(
        "watch2notif",
        icon=_build_tray_icon_image(),
        title="watch2notif",
        menu=pystray.Menu(menu_items),
    )
    icon.run()


def main() -> None:
    if not CONFIG_FILE.exists():
        sys.exit("config.json manquant. Lance settings.py pour le creer.")

    lang = load_config().get("lang") or i18n.detect_default_lang()
    pause_event = threading.Event()
    update_state: dict = {"info": None}

    threading.Thread(target=poll_loop, args=(pause_event, update_state, lang), daemon=True).start()
    run_tray(lang, pause_event, update_state)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\narret demande, bye.")
