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
import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import i18n
import notify_backend
import self_update
import single_instance
import update_check
from providers import DEFAULT_KIND, PROVIDERS

# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# (sys._MEIPASS) une fois fige, pas vers le dossier de l'executable : c'est
# la aussi qu'il faut config.json/state/, a cote du .exe reel.
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent

CONFIG_FILE = BASE_DIR / "config.json"
STATE_DIR = BASE_DIR / "state"
STATE_SCHEMA_VERSION = 2
# Un flux peut publier une entree avec quelques minutes de retard ou plusieurs
# entrees a la meme seconde. On ne classe silencieusement comme "remontee
# ancienne" qu'une entree clairement anterieure au repere persiste.
BACKFILL_GRACE_SECONDS = 5 * 60
MAX_FUTURE_TIMESTAMP_SECONDS = 24 * 3600

# A l'inverse de BASE_DIR : les assets embarques (watch2notif.spec, datas=)
# vivent dans sys._MEIPASS une fois fige (le dossier _internal/ en mode
# dossier), pas a cote de l'executable.
RESOURCE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ICON_FILE = RESOURCE_DIR / "assets" / "watch2notif.png"

# En executable "windowed" (console=False, cf watch2notif.spec), Windows ne
# donne pas de console au process : sys.stdout/stderr valent None, et le
# moindre print() plante. On redirige alors vers un fichier de log a cote
# de l'executable, seul moyen de garder une trace d'un poller silencieux.
SELF_TEST_REQUESTED = "--self-test-version" in sys.argv[1:]
if sys.stdout is None and not SELF_TEST_REQUESTED:
    log_file = open(BASE_DIR / "watch2notif.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log_file
elif sys.stdout is not None:
    sys.stdout.reconfigure(line_buffering=True)


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def state_file(feed_key: str) -> Path:
    return STATE_DIR / f"{feed_key}.json"


@dataclass
class FeedState:
    seen_ids: set[str] = field(default_factory=set)
    pending_ids: set[str] = field(default_factory=set)
    newest_timestamp: float | None = None
    source_fingerprint: str | None = None
    legacy: bool = False


def _valid_timestamp(value, *, reject_far_future: bool = True) -> float | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp) or timestamp < 0:
        return None
    if reject_far_future and timestamp > time.time() + MAX_FUTURE_TIMESTAMP_SECONDS:
        return None
    return timestamp


def load_feed_state(feed_key: str) -> FeedState:
    path = state_file(feed_key)
    if not path.exists():
        return FeedState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        # Migration transparente des versions <= 0.1.1.
        return FeedState(seen_ids={str(value) for value in raw if value}, legacy=True)
    if not isinstance(raw, dict):
        raise ValueError(f"format d'etat invalide pour {feed_key}")
    seen = raw.get("seen_ids") or []
    if not isinstance(seen, list):
        raise ValueError(f"seen_ids invalide pour {feed_key}")
    pending = raw.get("pending_ids") or []
    if not isinstance(pending, list):
        raise ValueError(f"pending_ids invalide pour {feed_key}")
    seen_ids = {str(value) for value in seen if value}
    return FeedState(
        seen_ids=seen_ids,
        pending_ids={str(value) for value in pending if value} - seen_ids,
        # Un recul de l'horloge locale ne doit pas effacer un watermark deja
        # valide. La garde "date trop future" ne concerne que les donnees
        # nouvellement fournies par un flux potentiellement mal forme.
        newest_timestamp=_valid_timestamp(raw.get("newest_timestamp"), reject_far_future=False),
        source_fingerprint=str(raw.get("source_fingerprint") or "") or None,
    )


def save_feed_state(feed_key: str, state: FeedState) -> None:
    _write_json_atomic(
        state_file(feed_key),
        {
            "version": STATE_SCHEMA_VERSION,
            "seen_ids": sorted(state.seen_ids),
            "pending_ids": sorted(state.pending_ids - state.seen_ids),
            "newest_timestamp": state.newest_timestamp,
            # Empreinte seulement : une URL RSS privee ne doit jamais etre
            # recopiee en clair dans les fichiers d'etat.
            "source_fingerprint": state.source_fingerprint,
        },
    )


def load_seen_ids(feed_key: str) -> set[str]:
    """Compatibilite pour les appels/tests existants."""
    return load_feed_state(feed_key).seen_ids


def save_seen_ids(feed_key: str, seen_ids: set[str]) -> None:
    """Compatibilite : conserve le repere temporel s'il existe deja."""
    state = load_feed_state(feed_key) if state_file(feed_key).exists() else FeedState()
    state.seen_ids = set(seen_ids)
    state.pending_ids.difference_update(state.seen_ids)
    state.legacy = False
    save_feed_state(feed_key, state)


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


def _feed_fingerprint(feed: dict) -> str:
    kind = str(feed.get("kind") or DEFAULT_KIND)
    url = str(feed.get("url") or "")
    return hashlib.sha256(f"{kind}\0{url}".encode("utf-8")).hexdigest()


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
        return str(id_)
    link = entry.get("link")
    if link:
        return str(link)
    signature = f"{entry.get('title', '')}|{entry.get('summary', '')}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


def _entry_timestamp(entry) -> float | None:
    """Horodatage UTC d'une entree RSS/API, si le provider en expose un."""
    for key in ("published_parsed", "created_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                timestamp = _valid_timestamp(calendar.timegm(tuple(parsed)[:9]))
            except (TypeError, ValueError, OverflowError):
                timestamp = None
            if timestamp is not None:
                return timestamp

    for key in ("published", "created", "created_at", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        if isinstance(raw, (int, float)):
            timestamp = _valid_timestamp(raw)
            if timestamp is not None:
                return timestamp
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(str(raw))
            except (TypeError, ValueError, OverflowError):
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamp = _valid_timestamp(parsed.timestamp())
        if timestamp is not None:
            return timestamp
    return None


def poll_feed(feed: dict) -> None:
    key, label = feed["key"], feed["label"]
    first_run = not state_file(key).exists()
    state = load_feed_state(key)
    fingerprint = _feed_fingerprint(feed)
    source_changed = bool(
        state.source_fingerprint and state.source_fingerprint != fingerprint
    )
    fingerprint_missing = state.source_fingerprint is None
    if source_changed:
        # La cle UI peut rester identique apres modification URL/provider.
        # L'ancien watermark n'a alors aucune signification pour la nouvelle
        # source : on la re-amorce comme un premier lancement, sans rafale.
        state = FeedState(source_fingerprint=fingerprint)
    else:
        state.source_fingerprint = fingerprint

    entries = fetch_entries(feed)
    records = []
    ids_in_batch = set()
    for entry in entries:
        entry_id = _entry_id(entry)
        if entry_id in ids_in_batch:
            continue
        ids_in_batch.add(entry_id)
        records.append((entry, entry_id, _entry_timestamp(entry)))
    timestamps = [timestamp for _entry, _entry_id_value, timestamp in records if timestamp is not None]
    current_newest = max(timestamps, default=None)

    if first_run or source_changed:
        state.seen_ids.update(entry_id for _entry, entry_id, _timestamp in records)
        state.newest_timestamp = current_newest
        state.legacy = False
        save_feed_state(key, state)
        reason = "source modifiee" if source_changed else "premier lancement"
        print(f"[{label}] {reason}: {len(entries)} item(s) amorces, aucune notif.")
        return

    stored_watermark = state.newest_timestamp
    was_legacy = state.legacy
    baseline = stored_watermark
    if baseline is None and state.legacy:
        known_timestamps = [
            timestamp
            for _entry, entry_id, timestamp in records
            if entry_id in state.seen_ids and timestamp is not None
        ]
        # Le dernier ID connu encore present peut etre tres ancien dans une
        # fenetre glissante. La date d'ecriture du state prouve que le poller
        # etait actif plus recemment : prendre le maximum des deux evite de
        # renotifier tous les elements intermediaires. On borne un mtime futur
        # en cas de correction de l'horloge systeme.
        cutoff_candidates = list(known_timestamps)
        try:
            state_mtime = _valid_timestamp(
                state_file(key).stat().st_mtime,
                reject_far_future=False,
            )
        except OSError:
            state_mtime = None
        if state_mtime is not None:
            cutoff_candidates.append(min(state_mtime, time.time()))
        baseline = max(cutoff_candidates, default=None)

    candidates = []
    backfilled = 0
    state_changed = False
    for entry, entry_id, timestamp in records:
        if entry_id in state.seen_ids:
            if entry_id in state.pending_ids:
                state.pending_ids.discard(entry_id)
                state_changed = True
            continue
        if entry_id in state.pending_ids:
            candidates.append((entry, entry_id, timestamp))
            continue
        is_old_backfill = (
            timestamp is not None
            and baseline is not None
            and timestamp < baseline - BACKFILL_GRACE_SECONDS
        )
        if is_old_backfill:
            state.seen_ids.add(entry_id)
            state.pending_ids.discard(entry_id)
            backfilled += 1
            state_changed = True
        else:
            candidates.append((entry, entry_id, timestamp))

    # Tout candidat devient "en attente" avant l'appel au backend. Ainsi, un
    # crash ou un echec de notification ne le transformera jamais en vieux
    # backfill silencieux lorsque le watermark aura avance entre-temps.
    for _entry, entry_id, _timestamp in candidates:
        if entry_id not in state.pending_ids:
            state.pending_ids.add(entry_id)
            state_changed = True

    state.newest_timestamp = baseline
    state.legacy = False
    if was_legacy or fingerprint_missing or state_changed or baseline != stored_watermark:
        save_feed_state(key, state)

    sent = 0
    for entry, entry_id, timestamp in reversed(candidates):
        try:
            notify(label, entry)
        except Exception as exc:
            print(f"[{label}] notif ratee pour une entree, on continue: {exc}")
            continue
        # Marquee vue seulement apres succes, et sauvee tout de suite : si une
        # notif suivante plante, celles deja envoyees ne repartent pas au
        # prochain cycle.
        state.seen_ids.add(entry_id)
        state.pending_ids.discard(entry_id)
        save_feed_state(key, state)
        sent += 1

    if current_newest is not None:
        next_watermark = max(
            value for value in (state.newest_timestamp, current_newest) if value is not None
        )
        if next_watermark != state.newest_timestamp:
            state.newest_timestamp = next_watermark
            save_feed_state(key, state)
    if backfilled:
        print(f"[{label}] {backfilled} ancienne(s) entree(s) memorisee(s) sans notification.")
    if sent:
        print(f"[{label}] {sent} nouvelle(s) notif(s) envoyee(s).")


class UpdateSignals(QObject):
    """Pont thread de polling/worker -> thread Qt."""

    available = Signal(object)
    prepared = Signal(object)
    failed = Signal(object)


def poll_loop(pause_event: threading.Event, update_signals: UpdateSignals) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    print("watch2notif demarre.")

    next_due: dict = {}
    notified_version = None
    emitted_version = object()

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
            lang = config.get("lang") or i18n.detect_default_lang()
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
            available_version = info.get("version") if info else None
            if available_version != emitted_version:
                emitted_version = available_version
                update_signals.available.emit(dict(info) if info else None)
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


def _show_windows_window(window) -> bool | None:
    """Synchronise l'etat Qt avec le HWND apres un clic de tray Windows.

    Sur Linux/macOS, Qt gere seul la fenetre. Sous Windows, on a observe
    QWidget.isVisible() == True alors que le HWND n'avait pas WS_VISIBLE ;
    ShowWindow remet explicitement les deux etats en phase.
    """
    if platform.system() != "Windows":
        return None
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = int(window.winId())
    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return bool(user32.IsWindowVisible(hwnd))


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


UPDATE_NONE = "none"
UPDATE_AVAILABLE = "available"
UPDATE_PROMPTING = "prompting"
UPDATE_DECLINED = "declined"
UPDATE_PREPARING = "preparing"
UPDATE_FAILED = "failed"


class TrayApp(QObject):
    def __init__(self, lang: str, pause_event: threading.Event, update_signals: UpdateSignals):
        super().__init__()
        self.lang = lang
        self.pause_event = pause_event
        self.update_signals = update_signals
        self.update_info = None
        self.update_status = UPDATE_NONE
        self.update_inflight = False
        self.prompted_versions: set[str] = set()
        self.update_dialog = None
        self.progress_dialog = None
        self.error_dialog = None
        self.settings_window = None

        self.update_signals.available.connect(
            self._on_update_available,
            Qt.ConnectionType.QueuedConnection,
        )
        self.update_signals.prepared.connect(
            self._on_update_prepared,
            Qt.ConnectionType.QueuedConnection,
        )
        self.update_signals.failed.connect(
            self._on_update_failed,
            Qt.ConnectionType.QueuedConnection,
        )

        self.tray = QSystemTrayIcon(_build_tray_icon())
        self.tray.setToolTip("watch2notif")
        self.menu = QMenu()
        # Ces QAction doivent rester les memes pendant toute la vie du tray.
        # Les detruire/recreer dans aboutToShow peut laisser Windows avec une
        # action native perimee : le clic ferme alors le menu sans appeler le
        # slot (constate sur l'action Reglages).
        self.pause_action = QAction("", self.menu, checkable=True)
        self.pause_action.toggled.connect(self._toggle_pause)
        self.settings_action = QAction("", self.menu)
        self.settings_action.triggered.connect(self._open_settings)
        self.update_action = QAction("", self.menu)
        self.update_action.triggered.connect(self._open_update_from_menu)
        self.help_action = QAction("", self.menu)
        self.help_action.triggered.connect(lambda _checked=False: open_url(HELP_URL))
        self.quit_action = QAction("", self.menu)
        self.quit_action.triggered.connect(QApplication.quit)
        self.menu.addActions(
            [
                self.pause_action,
                self.settings_action,
                self.update_action,
                self.help_action,
                self.quit_action,
            ]
        )
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.tray.setContextMenu(self.menu)
        self._rebuild_menu()
        self.tray.show()

    def _rebuild_menu(self) -> None:
        # Relu a chaque ouverture (pas seulement au demarrage) : sinon un
        # changement de langue fait dans les reglages ne se voit dans le
        # tray qu'au prochain redemarrage de l'appli.
        self.lang = self._current_lang()
        self.pause_action.setText(i18n.t("tray_pause", self.lang))
        signals_were_blocked = self.pause_action.blockSignals(True)
        self.pause_action.setChecked(self.pause_event.is_set())
        self.pause_action.blockSignals(signals_were_blocked)
        self.settings_action.setText(i18n.t("tray_settings", self.lang))

        info = self.update_info
        if info:
            automatic, _reason = self_update.can_install_automatically()
            if not automatic:
                key = "tray_update_view"
            elif self.update_status == UPDATE_PREPARING:
                key = "tray_update_downloading"
            elif self.update_status == UPDATE_FAILED:
                key = "tray_update_retry"
            else:
                key = "tray_update_install"
            self.update_action.setText(i18n.t(key, self.lang, version=info["version"]))
            self.update_action.setEnabled(self.update_status != UPDATE_PREPARING)
            self.update_action.setVisible(True)
        else:
            self.update_action.setEnabled(False)
            self.update_action.setVisible(False)

        self.help_action.setText(i18n.t("tray_help", self.lang))
        self.quit_action.setText(i18n.t("tray_quit", self.lang))

    def _toggle_pause(self, checked: bool) -> None:
        if checked:
            self.pause_event.set()
        else:
            self.pause_event.clear()

    def _current_lang(self) -> str:
        try:
            return load_config().get("lang") or i18n.detect_default_lang()
        except (OSError, json.JSONDecodeError, AttributeError):
            return self.lang or i18n.detect_default_lang()

    @Slot(object)
    def _on_update_available(self, info) -> None:
        if not info:
            # Ne pas arracher l'etat des mains d'une installation deja
            # preparee si un check concurrent devient temporairement vide.
            if not self.update_inflight:
                self.update_info = None
                self.update_status = UPDATE_NONE
                self._rebuild_menu()
            return

        info = dict(info)
        previous_version = self.update_info.get("version") if self.update_info else None
        version = str(info.get("version") or "")
        self.update_info = info
        if version != previous_version and not self.update_inflight:
            self.update_status = UPDATE_AVAILABLE
        self._rebuild_menu()

        if version and version not in self.prompted_versions and not self.update_inflight:
            self._show_update_prompt()

    @Slot(bool)
    def _open_update_from_menu(self, _checked: bool = False) -> None:
        if self.update_info and not self.update_inflight:
            self._show_update_prompt()

    def _show_update_prompt(self) -> bool:
        if not self.update_info or self.update_dialog is not None:
            return False
        info = dict(self.update_info)
        self.lang = self._current_lang()
        automatic, _reason = self_update.can_install_automatically()
        box = QMessageBox()
        box.setWindowIcon(_build_tray_icon())
        box.setIcon(QMessageBox.Icon.Question if automatic else QMessageBox.Icon.Information)
        box.setWindowModality(Qt.WindowModality.ApplicationModal)
        if automatic:
            box.setWindowTitle(i18n.t("update_prompt_title", self.lang))
            box.setText(
                i18n.t(
                    "update_prompt_body",
                    self.lang,
                    version=info["version"],
                    current=update_check.VERSION,
                )
            )
            accept_button = box.addButton(
                i18n.t("update_install_button", self.lang),
                QMessageBox.ButtonRole.AcceptRole,
            )
        else:
            box.setWindowTitle(i18n.t("update_source_title", self.lang))
            box.setText(i18n.t("update_source_body", self.lang))
            accept_button = box.addButton(
                i18n.t("update_open_release_button", self.lang),
                QMessageBox.ButtonRole.AcceptRole,
            )
        box.addButton(
            i18n.t("update_later_button", self.lang),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.finished.connect(
            lambda _result, dialog=box, accepted=accept_button, install=automatic, snapshot=info:
                self._finish_update_prompt(dialog, accepted, install, snapshot)
        )
        self.update_status = UPDATE_PROMPTING
        self.update_dialog = box
        self.prompted_versions.add(str(info.get("version") or ""))
        box.open()
        return True

    def _finish_update_prompt(self, dialog: QMessageBox, accept_button, automatic: bool, info: dict) -> None:
        clicked = dialog.clickedButton()
        self.update_dialog = None
        dialog.deleteLater()
        current_version = (self.update_info or {}).get("version")
        if current_version != info.get("version"):
            self.update_status = UPDATE_AVAILABLE
            self._rebuild_menu()
            if current_version not in self.prompted_versions:
                self._show_update_prompt()
            return
        if clicked is not accept_button:
            self.update_status = UPDATE_DECLINED
            self._rebuild_menu()
            return
        if not automatic:
            open_url(info.get("page"))
            self.update_status = UPDATE_DECLINED
            self._rebuild_menu()
            return
        self._start_update(info)

    def _start_update(self, info: dict) -> None:
        if not self.update_info or self.update_inflight:
            return
        self.lang = self._current_lang()
        version = info["version"]
        self.update_inflight = True
        self.update_status = UPDATE_PREPARING
        self._rebuild_menu()

        progress = QMessageBox()
        progress.setWindowIcon(_build_tray_icon())
        progress.setIcon(QMessageBox.Icon.Information)
        progress.setWindowTitle(i18n.t("update_progress_title", self.lang))
        progress.setText(i18n.t("update_progress_body", self.lang, version=version))
        progress.setStandardButtons(QMessageBox.StandardButton.NoButton)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.progress_dialog = progress
        progress.open()

        threading.Thread(target=self._prepare_update_worker, args=(version,), daemon=True).start()

    def _prepare_update_worker(self, expected_version: str) -> None:
        prepared = None
        try:
            # Un clic Installer force une relecture GitHub : le cache qui a
            # servi au signalement peut etre ancien ou ne pas encore contenir
            # digest/size (migration depuis les versions precedentes).
            latest = update_check.disponible(BASE_DIR, force=True)
            if not latest:
                raise self_update.UpdateError("missing_asset", "la release n'est plus disponible")
            if latest.get("version") != expected_version:
                self.update_signals.failed.emit({"code": "version_changed", "info": latest})
                return
            prepared = self_update.prepare_update(latest, update_check.DEPOT)
            self_update.launch_prepared_update(prepared)
            self.update_signals.prepared.emit(prepared)
        except self_update.UpdateError as exc:
            if prepared is not None:
                self_update.cleanup_prepared(prepared)
            self.update_signals.failed.emit(exc.payload())
        except Exception as exc:
            if prepared is not None:
                self_update.cleanup_prepared(prepared)
            self.update_signals.failed.emit({"code": "prepare_failed", "detail": str(exc)})

    @Slot(object)
    def _on_update_prepared(self, prepared) -> None:
        try:
            self_update.commit_prepared_update(prepared)
        except self_update.UpdateError as exc:
            self_update.abort_prepared_update(prepared)
            self._on_update_failed(exc.payload())
            return
        if self.progress_dialog is not None:
            self.progress_dialog.done(0)
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        QApplication.quit()

    @Slot(object)
    def _on_update_failed(self, error) -> None:
        if self.progress_dialog is not None:
            self.progress_dialog.done(0)
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        self.update_inflight = False
        if (error or {}).get("code") == "version_changed":
            self.update_status = UPDATE_AVAILABLE
            self._on_update_available((error or {}).get("info"))
            return
        self.update_status = UPDATE_FAILED
        self._rebuild_menu()
        self.lang = self._current_lang()

        code = str((error or {}).get("code") or "prepare_failed")
        detail = str((error or {}).get("detail") or "")
        if detail:
            print(f"mise a jour echouee [{code}]: {detail}")
        if code == "download_failed":
            error_key = "update_error_download"
        elif code in {"integrity_failed", "unsafe_archive", "invalid_payload"}:
            error_key = "update_error_integrity"
        elif code in {"unsupported_target", "missing_asset", "invalid_asset", "source_mode"}:
            error_key = "update_error_compatibility"
        elif code in {"helper_failed", "unsafe_install"}:
            error_key = "update_error_installer"
        else:
            error_key = "update_error_generic"
        friendly_error = i18n.t(error_key, self.lang)
        box = QMessageBox()
        box.setWindowIcon(_build_tray_icon())
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(i18n.t("update_error_title", self.lang))
        box.setText(i18n.t("update_error_body", self.lang, error=friendly_error))
        release_button = box.addButton(
            i18n.t("update_open_release_button", self.lang),
            QMessageBox.ButtonRole.ActionRole,
        )
        box.addButton(i18n.t("update_close_button", self.lang), QMessageBox.ButtonRole.RejectRole)
        box.finished.connect(
            lambda _result, dialog=box, button=release_button: self._finish_error_dialog(dialog, button)
        )
        self.error_dialog = box
        box.open()

    def _finish_error_dialog(self, dialog: QMessageBox, release_button) -> None:
        if dialog.clickedButton() is release_button:
            open_url((self.update_info or {}).get("page"))
        self.error_dialog = None
        dialog.deleteLater()

    @Slot(bool)
    def _open_settings(self, _checked: bool = False) -> None:
        # triggered() est emis avant que le menu natif du tray ait fini de
        # se fermer. Sous Windows, afficher une autre top-level window dans
        # cette pile d'evenements peut la laisser creee mais cachee. Reporter
        # l'ouverture au tour suivant de la boucle Qt evite cette course.
        print("ouverture des reglages demandee depuis le tray.")
        QTimer.singleShot(0, self._show_settings)

    @Slot()
    def _show_settings(self) -> None:
        import settings

        if self.settings_window is None:
            self.settings_window = settings.SettingsWindow(settings.load_config())
        # show() seul ne restaure pas une fenetre minimisee. showNormal()
        # couvre a la fois la premiere ouverture, une fermeture et un clic
        # ulterieur depuis le tray.
        self.settings_window.showNormal()
        self.settings_window.raise_()
        self.settings_window.activateWindow()
        _show_windows_window(self.settings_window)
        # Certains menus natifs terminent leur masquage apres le prochain
        # evenement Qt. Une seconde verification courte rend l'ouverture
        # deterministe sans delai perceptible pour l'utilisateur.
        QTimer.singleShot(150, self._ensure_settings_visible)

    @Slot()
    def _ensure_settings_visible(self) -> None:
        if self.settings_window is None:
            return
        if not self.settings_window.isVisible() or self.settings_window.isMinimized():
            self.settings_window.showNormal()
        self.settings_window.raise_()
        self.settings_window.activateWindow()
        native_visible = _show_windows_window(self.settings_window)
        print(
            "fenetre reglages visible: "
            f"qt={self.settings_window.isVisible()}, native={native_visible}"
        )


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
    update_signals = UpdateSignals()

    # Sans ca, fermer la fenetre de reglages (ouverte depuis le tray)
    # quitterait toute l'appli : ce n'est pas une "fenetre principale",
    # le tray doit continuer a tourner apres sa fermeture.
    app.setQuitOnLastWindowClosed(False)
    # La reference doit survivre a main() (tant que la boucle Qt tourne) :
    # sans variable pour la retenir, TrayApp et son QSystemTrayIcon sont
    # garbage-collectes des la fin de cette ligne, et l'icone disparait
    # silencieusement (aucune erreur, isVisible() valait bien True juste
    # avant) - constate en debuggant ce fichier meme.
    tray_app = TrayApp(lang, pause_event, update_signals)  # noqa: F841

    threading.Thread(target=poll_loop, args=(pause_event, update_signals), daemon=True).start()

    app.exec()


if __name__ == "__main__":
    if "--self-test-version" in sys.argv[1:]:
        try:
            expected_version = sys.argv[sys.argv.index("--self-test-version") + 1]
        except (ValueError, IndexError):
            raise SystemExit(2)
        if expected_version != update_check.VERSION or not ICON_FILE.is_file():
            raise SystemExit(3)
        raise SystemExit(0)
    if "--settings" in sys.argv[1:]:
        import settings

        settings.main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print("\narret demande, bye.")
