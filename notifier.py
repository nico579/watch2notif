"""Poll the sources enabled in config.json (RSS/Atom feeds, GitHub issues,
see providers/) and fire a desktop notification for anything new.
Cross-platform (Windows/Linux/Mac). Runs the polling in a background
thread and a Qt system tray icon (pause/settings/quit) on the main
thread.

Single binary, single GUI toolkit: the tray uses QSystemTrayIcon rather
than a separate library (pystray) precisely so that Qt is the only GUI
dependency in the whole executable — mixing pystray and PySide6 in one
PyInstaller build makes shiboken's global import hook (which activates
process-wide as soon as Qt is anywhere in the dependency graph, not only
once actually imported) crash pystray's win32 backend on a `six`
metapath incompatibility. One toolkit sidesteps that at the root instead
of working around it. Settings opens as a plain widget in this same
process (see run_tray's _open_settings); `--settings` (bottom of this
file) still launches just the panel standalone, for a shortcut or CLI use.
"""
import hashlib
import os
import json
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import i18n
import notify_backend
import single_instance
import update_check
from providers import DEFAULT_KIND, PROVIDERS

# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# (sys._MEIPASS) une fois fige, pas vers le dossier de l'executable : c'est
# la aussi qu'il faut config.json/state/, a cote du .exe reel.
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent

CONFIG_FILE = BASE_DIR / "config.json"
STATE_DIR = BASE_DIR / "state"

# A l'inverse de BASE_DIR : les assets embarques (watch2notif.spec, datas=)
# vivent dans sys._MEIPASS une fois fige (le dossier _internal/ en mode
# dossier), pas a cote de l'executable.
RESOURCE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ICON_FILE = RESOURCE_DIR / "assets" / "watch2notif.png"

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
    _write_json_atomic(state_file(feed_key), sorted(seen_ids))


def _write_json_atomic(path: Path, data) -> None:
    """Ecrit dans un fichier temporaire puis renomme : un lecteur concurrent
    (poll_loop tournant pendant un save_config depuis settings.py, par
    exemple) ne peut jamais voir un fichier tronque/partiellement ecrit."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


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


def _entry_id(entry) -> str:
    """entry.id peut manquer (RSS 2.0 sans <guid>) : on retombe sur le lien,
    puis sur un hash stable du contenu plutot que de planter/reperdre
    l'entree a chaque cycle. getattr (pas .get) : providers.base.Entry
    garde "id" en attribut direct, pas dans les clefs que .get() lit."""
    id_ = getattr(entry, "id", None)
    if id_:
        return id_
    link = entry.get("link")
    if link:
        return link
    signature = f"{entry.get('title', '')}|{entry.get('summary', '')}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


def poll_feed(feed: dict) -> None:
    key, label = feed["key"], feed["label"]
    first_run = not state_file(key).exists()
    seen_ids = load_seen_ids(key)

    entries = fetch_entries(feed)

    if first_run:
        seen_ids.update(_entry_id(e) for e in entries)
        save_seen_ids(key, seen_ids)
        print(f"[{label}] premier lancement: {len(entries)} item(s) amorces, aucune notif.")
        return

    new_entries = [e for e in entries if _entry_id(e) not in seen_ids]
    sent = 0
    for entry in reversed(new_entries):
        entry_id = _entry_id(entry)
        try:
            notify(label, entry)
        except Exception as exc:
            print(f"[{label}] notif ratee pour une entree, on continue: {exc}")
            continue
        # Marquee vue seulement apres succes, et sauvee tout de suite : si une
        # notif suivante plante, celles deja envoyees ne repartent pas au
        # prochain cycle.
        seen_ids.add(entry_id)
        save_seen_ids(key, seen_ids)
        sent += 1
    if sent:
        print(f"[{label}] {sent} nouvelle(s) notif(s) envoyee(s).")


def poll_loop(pause_event: threading.Event, update_state: dict, lang: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    print("watch2notif demarre.")

    next_due: dict = {}
    notified_version = None

    while True:
        if pause_event.is_set():
            time.sleep(5)
            continue

        # Try/except large et non specifique : un config.json corrompu par
        # une ecriture concurrente, ou une panne reseau sur le check de
        # version, ne doivent jamais tuer ce thread daemon. Le tray, lui,
        # continuerait de tourner sans plus rien poller, en ayant l'air
        # normal - constate en revue de code, pas en test.
        try:
            config = load_config()
            default_interval = config.get("poll_interval_seconds", 60)
            active_feeds = [f for f in config["feeds"] if f["enabled"] and f["url"]]

            if not active_feeds:
                print("aucune source active dans config.json (lance --settings).")

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
        except Exception as exc:
            print(f"erreur dans le cycle de poll, on reessaie au prochain: {exc}")

        time.sleep(5)


def _build_tray_icon() -> QIcon:
    return QIcon(str(ICON_FILE))


def open_url(url: str) -> None:
    if not url:
        return
    if platform.system() == "Windows":
        os.startfile(url)
    elif platform.system() == "Darwin":
        subprocess.run(["open", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


HELP_URL = f"https://github.com/{update_check.DEPOT}#readme"


class TrayApp:
    def __init__(self, lang: str, pause_event: threading.Event, update_state: dict):
        self.lang = lang
        self.pause_event = pause_event
        self.update_state = update_state
        self.settings_window = None

        self.tray = QSystemTrayIcon(_build_tray_icon())
        self.tray.setToolTip("watch2notif")
        self.menu = QMenu()
        # Menu reconstruit a chaque ouverture : c'est ainsi qu'on affiche
        # l'entree "nouvelle version" seulement quand elle existe (meme
        # esprit que le menu dynamique pystray remplace ici).
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.tray.setContextMenu(self.menu)
        self._rebuild_menu()
        self.tray.show()

    def _rebuild_menu(self) -> None:
        self.menu.clear()

        pause_action = QAction(i18n.t("tray_pause", self.lang), self.menu, checkable=True)
        pause_action.setChecked(self.pause_event.is_set())
        pause_action.toggled.connect(self._toggle_pause)
        self.menu.addAction(pause_action)

        settings_action = QAction(i18n.t("tray_settings", self.lang), self.menu)
        settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(settings_action)

        info = self.update_state.get("info")
        if info:
            update_action = QAction(i18n.t("tray_update_available", self.lang, version=info["version"]), self.menu)
            update_action.triggered.connect(lambda: open_url(info.get("page")))
            self.menu.addAction(update_action)

        help_action = QAction(i18n.t("tray_help", self.lang), self.menu)
        help_action.triggered.connect(lambda: open_url(HELP_URL))
        self.menu.addAction(help_action)

        quit_action = QAction(i18n.t("tray_quit", self.lang), self.menu)
        quit_action.triggered.connect(QApplication.quit)
        self.menu.addAction(quit_action)

    def _toggle_pause(self, checked: bool) -> None:
        if checked:
            self.pause_event.set()
        else:
            self.pause_event.clear()

    def _open_settings(self) -> None:
        import settings

        if self.settings_window is None:
            self.settings_window = settings.SettingsWindow(settings.load_config())
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()


def main() -> None:
    if not single_instance.acquire(BASE_DIR):
        # Autostart + lancement manuel, ou double-clic accidentel : pas
        # d'erreur bruyante pour un poller de fond, on cede juste la place
        # a l'instance deja active.
        print("une instance de watch2notif tourne deja, arret.")
        return

    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_FILE)))

    if not CONFIG_FILE.exists():
        # Premier lancement d'un bundle telecharge (pas de config.json a
        # cote de l'exe) : ouvrir directement les reglages plutot que
        # quitter en silence - en windowed (console=False) personne ne
        # verrait jamais un message d'erreur en ligne de commande.
        import settings

        first_run_window = settings.SettingsWindow(settings.load_config())
        first_run_window.show()
        app.exec()
        if not CONFIG_FILE.exists():
            return

    lang = load_config().get("lang") or i18n.detect_default_lang()
    pause_event = threading.Event()
    update_state: dict = {"info": None}

    # Sans ca, fermer la fenetre de reglages (ouverte depuis le tray)
    # quitterait toute l'appli : ce n'est pas une "fenetre principale",
    # le tray doit continuer a tourner apres sa fermeture.
    app.setQuitOnLastWindowClosed(False)
    # La reference doit survivre a main() (tant que la boucle Qt tourne) :
    # sans variable pour la retenir, TrayApp et son QSystemTrayIcon sont
    # garbage-collectes des la fin de cette ligne, et l'icone disparait
    # silencieusement (aucune erreur, isVisible() valait bien True juste
    # avant) - constate en debuggant ce fichier meme.
    tray_app = TrayApp(lang, pause_event, update_state)  # noqa: F841

    threading.Thread(target=poll_loop, args=(pause_event, update_state, lang), daemon=True).start()

    app.exec()


if __name__ == "__main__":
    if "--settings" in sys.argv[1:]:
        import settings

        settings.main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print("\narret demande, bye.")
