"""Tray window listing the desktop notifications actually sent (see
notification_history.py). Double-click a row to reopen its link, same
as clicking the original toast."""
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import i18n
import notification_history

RESOURCE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ICON_FILE = RESOURCE_DIR / "assets" / "watch2notif.png"

COL_DATE, COL_SOURCE, COL_TITLE = range(3)


def open_url(url: str) -> None:
    if not url:
        return
    if platform.system() == "Windows":
        os.startfile(url)
    elif platform.system() == "Darwin":
        subprocess.run(["open", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


class HistoryWindow(QWidget):
    def __init__(self, lang: str):
        super().__init__()
        self.lang = lang
        self.setMinimumSize(700, 400)
        self.setWindowIcon(QIcon(str(ICON_FILE)))
        self._build_ui()
        self.reload()

    def t(self, key: str, **kwargs) -> str:
        return i18n.t(key, self.lang, **kwargs)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.table = QTableWidget(0, 3)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(COL_DATE, 140)
        self.table.setColumnWidth(COL_SOURCE, 180)
        self.table.cellDoubleClicked.connect(self._open_row)
        root.addWidget(self.table)

        button_row = QHBoxLayout()
        self.clear_button = QPushButton()
        self.clear_button.clicked.connect(self._clear)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

        self._apply_language()

    def _apply_language(self) -> None:
        self.setWindowTitle(self.t("history_window_title"))
        self.hint_label.setText(self.t("history_hint_text"))
        self.table.setHorizontalHeaderLabels([
            self.t("history_header_date"), self.t("history_header_source"), self.t("history_header_title"),
        ])
        self.clear_button.setText(self.t("history_clear_button"))
        self.close_button.setText(self.t("history_close_button"))

    def reload(self, lang: str = None) -> None:
        if lang is not None:
            self.lang = lang
        self._apply_language()
        entries = notification_history.load()
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            timestamp = entry.get("timestamp")
            date_text = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M") if timestamp else ""
            self.table.setItem(row, COL_DATE, QTableWidgetItem(date_text))
            self.table.setItem(row, COL_SOURCE, QTableWidgetItem(entry.get("feed_label", "")))
            title_item = QTableWidgetItem(entry.get("title", ""))
            title_item.setData(Qt.ItemDataRole.UserRole, entry.get("link", ""))
            self.table.setItem(row, COL_TITLE, title_item)

    def _open_row(self, row: int, _column: int) -> None:
        item = self.table.item(row, COL_TITLE)
        if item:
            open_url(item.data(Qt.ItemDataRole.UserRole))

    def _clear(self) -> None:
        notification_history.clear()
        self.reload()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_FILE)))
    window = HistoryWindow(i18n.detect_default_lang())
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
