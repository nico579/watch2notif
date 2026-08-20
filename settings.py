"""Settings panel (Qt/PySide6): choose sources to watch (RSS/Atom, GitHub
issues, see providers/), their per-source polling interval, and toggle
autostart. Generic tool: any RSS feed works, config.json comes prefilled
with the Reddit inbox feeds and a GitHub issues example, but sources can
be freely added/removed. Saves to config.json, read by notifier.py.

Qt over tkinter for this one screen: a real table (QTableWidget) gives
native, user-draggable column resize and proper widgets per cell
(checkbox, combobox, spin box) for free, which tkinter's grid/pack model
doesn't offer without a lot of custom plumbing.
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

import autostart_manager
import i18n
from providers import DEFAULT_KIND, PROVIDERS

# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# une fois fige, pas vers le dossier de l'executable : config.json doit
# vivre a cote du .exe reel.
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

# A l'inverse de BASE_DIR : les assets embarques (watch2notif.spec, datas=)
# vivent dans sys._MEIPASS une fois fige, pas a cote de l'executable.
RESOURCE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ICON_FILE = RESOURCE_DIR / "assets" / "watch2notif.png"

KIND_LABELS = {kind: provider.LABEL for kind, provider in PROVIDERS.items()}
KIND_BY_LABEL = {v: k for k, v in KIND_LABELS.items()}
KIND_INTERVALS = {kind: getattr(provider, "DEFAULT_INTERVAL_SECONDS", 60) for kind, provider in PROVIDERS.items()}

COL_ACTIVE, COL_KIND, COL_NAME, COL_URL, COL_INTERVAL, COL_REMOVE = range(6)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"poll_interval_seconds": 60, "feeds": [], "lang": i18n.detect_default_lang()}


def save_config(config: dict) -> None:
    # Fichier temporaire puis renommage : notifier.py (poll_loop) relit
    # config.json en continu dans un autre process, il ne doit jamais
    # tomber sur une ecriture partielle/tronquee.
    tmp = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def slugify(label: str, existing_keys: set) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or "source"
    candidate = slug
    counter = 2
    while candidate in existing_keys:
        candidate = f"{slug}_{counter}"
        counter += 1
    return candidate


class SettingsWindow(QWidget):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.lang = config.get("lang") or i18n.detect_default_lang()
        self._translated_widgets: list[tuple] = []  # (widget, key)
        self.setMinimumWidth(900)
        self.setWindowIcon(QIcon(str(ICON_FILE)))

        self._build_ui()
        for feed in self.config["feeds"]:
            self._add_row(
                key=feed.get("key", ""),
                label=feed.get("label", ""),
                url=feed.get("url", ""),
                enabled=feed.get("enabled", False),
                kind=feed.get("kind", DEFAULT_KIND),
                interval_seconds=feed.get("interval_seconds"),
            )
        self._apply_language()

    def t(self, key: str, **kwargs) -> str:
        return i18n.t(key, self.lang, **kwargs)

    def _register(self, widget, key: str) -> None:
        self._translated_widgets.append((widget, key))

    def _apply_language(self) -> None:
        self.setWindowTitle(self.t("window_title"))
        for widget, key in self._translated_widgets:
            widget.setText(self.t(key))
        self.table.setHorizontalHeaderLabels([
            self.t("header_active"), self.t("header_kind"), self.t("header_name"),
            self.t("header_url"), self.t("header_interval"), "",
        ])
        for code, btn in self._lang_buttons.items():
            btn.setChecked(code == self.lang)

    def _set_lang(self, code: str) -> None:
        self.lang = code
        self._apply_language()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        lang_row = QHBoxLayout()
        lang_row.addStretch()
        self._lang_buttons = {}
        # setChecked() (etat persistant) + groupe exclusif, pas setDown()
        # (etat visuel transitoire, meant pour un clic maintenu) : sans ca
        # les deux boutons pouvaient rester enfonces en meme temps.
        lang_group = QButtonGroup(self)
        lang_group.setExclusive(True)
        for code, text in (("fr", "FR"), ("en", "EN")):
            btn = QPushButton(text)
            btn.setFixedWidth(36)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, c=code: self._set_lang(c))
            lang_group.addButton(btn)
            lang_row.addWidget(btn)
            self._lang_buttons[code] = btn
        root.addLayout(lang_row)

        self.autostart_check = QCheckBox()
        self.autostart_check.setChecked(autostart_manager.is_enabled())
        self._register(self.autostart_check, "autostart_label")
        root.addWidget(self.autostart_check)

        self.table = QTableWidget(0, 6)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setMinimumHeight(200)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(COL_ACTIVE, 50)
        self.table.setColumnWidth(COL_KIND, 120)
        self.table.setColumnWidth(COL_NAME, 180)
        self.table.setColumnWidth(COL_URL, 330)
        self.table.setColumnWidth(COL_INTERVAL, 80)
        self.table.setColumnWidth(COL_REMOVE, 30)
        root.addWidget(self.table)

        add_row = QHBoxLayout()
        add_button = QPushButton()
        add_button.clicked.connect(lambda: self._add_row())
        self._register(add_button, "add_feed_button")
        add_row.addWidget(add_button)
        add_row.addStretch()
        root.addLayout(add_row)

        note = QLabel()
        note.setWordWrap(True)
        self._register(note, "note_text")
        root.addWidget(note)

        save_row = QHBoxLayout()
        save_row.addStretch()
        save_button = QPushButton()
        save_button.clicked.connect(self.on_save)
        self._register(save_button, "save_button")
        save_row.addWidget(save_button)
        root.addLayout(save_row)

    def _add_row(self, key: str = "", label: str = "", url: str = "", enabled: bool = False,
                 kind: str = DEFAULT_KIND, interval_seconds: int = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        active_cell = QWidget()
        active_layout = QHBoxLayout(active_cell)
        active_layout.setAlignment(Qt.AlignCenter)
        active_layout.setContentsMargins(0, 0, 0, 0)
        checkbox = QCheckBox()
        checkbox.setChecked(enabled)
        checkbox._feed_key = key
        active_layout.addWidget(checkbox)
        self.table.setCellWidget(row, COL_ACTIVE, active_cell)

        combo = QComboBox()
        combo.addItems(list(KIND_LABELS.values()))
        combo.setCurrentText(KIND_LABELS.get(kind, kind))
        self.table.setCellWidget(row, COL_KIND, combo)

        name_edit = QLineEdit(label)
        self.table.setCellWidget(row, COL_NAME, name_edit)

        url_edit = QLineEdit(url)
        # Sans ca, le curseur (place en fin de texte a la construction) fait
        # scroller le champ pour rester visible : on ne voit que la fin de
        # l'URL au lieu du debut.
        url_edit.setCursorPosition(0)
        self.table.setCellWidget(row, COL_URL, url_edit)

        # Auto : le spin box suit le defaut du type tant que l'utilisateur ne
        # l'a pas modifie lui-meme.
        interval_auto = {"value": interval_seconds is None}
        interval_spin = QSpinBox()
        interval_spin.setRange(5, 86400)
        interval_spin.setValue(interval_seconds or KIND_INTERVALS.get(kind, 60))
        interval_spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setCellWidget(row, COL_INTERVAL, interval_spin)

        def on_kind_change(text, interval_auto=interval_auto, interval_spin=interval_spin):
            if interval_auto["value"]:
                interval_spin.blockSignals(True)
                interval_spin.setValue(KIND_INTERVALS.get(KIND_BY_LABEL.get(text, DEFAULT_KIND), 60))
                interval_spin.blockSignals(False)

        combo.currentTextChanged.connect(on_kind_change)
        interval_spin.valueChanged.connect(lambda _v, a=interval_auto: a.update(value=False))

        remove_button = QPushButton("x")
        remove_button.setFixedWidth(24)
        remove_button.clicked.connect(lambda: self._remove_row(remove_button))
        self.table.setCellWidget(row, COL_REMOVE, remove_button)

    def _remove_row(self, button: QPushButton) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, COL_REMOVE) is button:
                self.table.removeRow(row)
                return

    def on_save(self) -> None:
        existing_keys: set = set()
        feeds = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, COL_ACTIVE).findChild(QCheckBox)
            combo = self.table.cellWidget(row, COL_KIND)
            name_edit = self.table.cellWidget(row, COL_NAME)
            url_edit = self.table.cellWidget(row, COL_URL)
            interval_spin = self.table.cellWidget(row, COL_INTERVAL)

            label = name_edit.text().strip()
            url = url_edit.text().strip()
            if not label and not url:
                continue
            key = getattr(checkbox, "_feed_key", "") or slugify(label, existing_keys)
            # Reaffecte au widget : sans ca, une ligne neuve (pas encore
            # rechargee depuis config.json) se voit generer une NOUVELLE cle
            # a chaque Sauvegarder si son nom a change entre-temps, perdant
            # l'historique de dedup de la precedente.
            checkbox._feed_key = key
            existing_keys.add(key)
            feeds.append({
                "key": key,
                "label": label or key,
                "url": url,
                "enabled": checkbox.isChecked(),
                "kind": KIND_BY_LABEL.get(combo.currentText(), DEFAULT_KIND),
                "interval_seconds": interval_spin.value(),
            })

        self.config["feeds"] = feeds
        self.config["lang"] = self.lang
        save_config(self.config)

        try:
            wants_autostart = self.autostart_check.isChecked()
            currently_enabled = autostart_manager.is_enabled()
            if wants_autostart and not currently_enabled:
                autostart_manager.enable()
            elif not wants_autostart and currently_enabled:
                autostart_manager.disable()
        except Exception as exc:
            QMessageBox.critical(self, self.t("autostart_error_title"), self.t("autostart_error_msg", error=exc))
            return

        QMessageBox.information(self, self.t("ok_title"), self.t("ok_msg"))


def main() -> None:
    config = load_config()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_FILE)))
    window = SettingsWindow(config)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
