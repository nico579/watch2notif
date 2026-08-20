"""Panneau de reglage : choisir les sources a surveiller (RSS/Atom, issues
GitHub, voir providers/), leur intervalle de polling individuel, et
activer le demarrage automatique. Outil generique : n'importe quel flux
RSS marche, config.json vient preremplli avec les flux inbox Reddit et un
exemple GitHub issues, mais on peut ajouter/retirer librement.
Sauvegarde dans config.json, lu par notifier.py.
"""
import json
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import autostart_manager
import i18n
from providers import DEFAULT_KIND, PROVIDERS

# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# une fois fige, pas vers le dossier de l'executable : config.json doit
# vivre a cote du .exe reel.
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

KIND_LABELS = {kind: provider.LABEL for kind, provider in PROVIDERS.items()}
KIND_HINTS = {kind: provider.SOURCE_HINT for kind, provider in PROVIDERS.items()}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"poll_interval_seconds": 60, "feeds": [], "lang": i18n.detect_default_lang()}


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def slugify(label: str, existing_keys: set) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or "source"
    candidate = slug
    counter = 2
    while candidate in existing_keys:
        candidate = f"{slug}_{counter}"
        counter += 1
    return candidate


class FeedRow:
    """Une ligne editable (actif / type / label / url / intervalle / supprimer)."""

    def __init__(self, parent: tk.Widget, on_remove, key: str = "", label: str = "",
                 url: str = "", enabled: bool = False, kind: str = DEFAULT_KIND,
                 interval_seconds: int = None):
        self.key = key
        self.removed = False
        self.frame = ttk.Frame(parent, padding=(0, 3))
        self.frame.pack(fill="x")

        self.enabled_var = tk.BooleanVar(value=enabled)
        ttk.Checkbutton(self.frame, variable=self.enabled_var, width=3).pack(side="left")

        self.kind_var = tk.StringVar(value=KIND_LABELS.get(kind, kind))
        self._kind_by_label = {v: k for k, v in KIND_LABELS.items()}
        kind_box = ttk.Combobox(self.frame, textvariable=self.kind_var, values=list(KIND_LABELS.values()),
                                 state="readonly", width=13)
        kind_box.pack(side="left", padx=2)
        kind_box.bind("<<ComboboxSelected>>", lambda e: self._on_kind_change())

        self.label_var = tk.StringVar(value=label)
        ttk.Entry(self.frame, textvariable=self.label_var, width=20).pack(side="left", padx=2)

        self.url_var = tk.StringVar(value=url)
        self.url_entry = ttk.Entry(self.frame, textvariable=self.url_var, width=32)
        self.url_entry.pack(side="left", padx=2)

        self.interval_var = tk.StringVar(value=str(interval_seconds) if interval_seconds else "")
        ttk.Entry(self.frame, textvariable=self.interval_var, width=6).pack(side="left", padx=2)

        ttk.Button(self.frame, text="x", width=3, command=lambda: on_remove(self)).pack(side="left", padx=2)

        self._on_kind_change()

    def _on_kind_change(self) -> None:
        kind = self.kind
        self.url_entry.config(show="*" if kind == "rss" else "")

    @property
    def kind(self) -> str:
        return self._kind_by_label.get(self.kind_var.get(), DEFAULT_KIND)

    def destroy(self) -> None:
        self.removed = True
        self.frame.destroy()


class SettingsApp:
    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.config = config
        self.rows: list[FeedRow] = []
        self.lang = config.get("lang") or i18n.detect_default_lang()
        self._translated_widgets: list[tuple] = []  # (widget, key)
        self.root.geometry("850x540")

        self._build_lang_toggle()
        self._build_interval_row()
        self._build_autostart_row()
        self._build_feed_list()
        self._build_buttons()

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
        self.root.title(self.t("window_title"))
        for widget, key in self._translated_widgets:
            widget.config(text=self.t(key))
        for button, code in self._lang_buttons:
            button.state(["pressed"] if code == self.lang else ["!pressed"])

    def _set_lang(self, code: str) -> None:
        self.lang = code
        self._apply_language()

    def _build_lang_toggle(self) -> None:
        frame = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        frame.pack(fill="x")
        group = ttk.Frame(frame)
        group.pack(side="right")
        self._lang_buttons = []
        for code, text in (("fr", "FR"), ("en", "EN")):
            btn = ttk.Button(group, text=text, width=4, command=lambda c=code: self._set_lang(c))
            btn.pack(side="left")
            self._lang_buttons.append((btn, code))

    def _build_interval_row(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="x")
        label = ttk.Label(frame)
        label.pack(side="left")
        self._register(label, "interval_label")
        self.interval_var = tk.StringVar(value=str(self.config.get("poll_interval_seconds", 60)))
        ttk.Entry(frame, textvariable=self.interval_var, width=8).pack(side="left", padx=6)

    def _build_autostart_row(self) -> None:
        frame = ttk.Frame(self.root, padding=(10, 0))
        frame.pack(fill="x")
        self.autostart_var = tk.BooleanVar(value=autostart_manager.is_enabled())
        check = ttk.Checkbutton(frame, variable=self.autostart_var)
        check.pack(side="left")
        self._register(check, "autostart_label")

    def _build_feed_list(self) -> None:
        header = ttk.Frame(self.root, padding=(10, 8, 10, 2))
        header.pack(fill="x")
        active_label = ttk.Label(header, width=5)
        active_label.pack(side="left")
        self._register(active_label, "header_active")
        kind_label = ttk.Label(header, width=15)
        kind_label.pack(side="left")
        self._register(kind_label, "header_kind")
        name_label = ttk.Label(header, width=21)
        name_label.pack(side="left")
        self._register(name_label, "header_name")
        url_label = ttk.Label(header, width=32)
        url_label.pack(side="left")
        self._register(url_label, "header_url")
        interval_label = ttk.Label(header, width=11)
        interval_label.pack(side="left")
        self._register(interval_label, "header_interval")

        outer = ttk.Frame(self.root, padding=(10, 0))
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.feed_container = ttk.Frame(canvas)

        self.feed_container.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.feed_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        add_frame = ttk.Frame(self.root, padding=10)
        add_frame.pack(fill="x")
        add_button = ttk.Button(add_frame, command=lambda: self._add_row())
        add_button.pack(side="left")
        self._register(add_button, "add_feed_button")

        note = ttk.Label(self.root, padding=(10, 0, 10, 10), wraplength=780)
        note.pack(fill="x")
        self._register(note, "note_text")

    def _add_row(self, key: str = "", label: str = "", url: str = "", enabled: bool = False,
                 kind: str = DEFAULT_KIND, interval_seconds: int = None) -> None:
        row = FeedRow(self.feed_container, self._remove_row, key=key, label=label, url=url,
                      enabled=enabled, kind=kind, interval_seconds=interval_seconds)
        self.rows.append(row)

    def _remove_row(self, row: FeedRow) -> None:
        row.destroy()
        self.rows.remove(row)

    def _build_buttons(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="x")
        save_button = ttk.Button(frame, command=self.on_save)
        save_button.pack(side="right")
        self._register(save_button, "save_button")

    def on_save(self) -> None:
        try:
            interval = int(self.interval_var.get())
            if interval < 5:
                raise ValueError
        except ValueError:
            messagebox.showerror(self.t("error_title"), self.t("error_interval_msg"))
            return

        existing_keys: set = set()
        feeds = []
        for row in self.rows:
            label = row.label_var.get().strip()
            url = row.url_var.get().strip()
            if not label and not url:
                continue
            key = row.key or slugify(label, existing_keys)
            existing_keys.add(key)
            row_interval = row.interval_var.get().strip()
            feeds.append({
                "key": key,
                "label": label or key,
                "url": url,
                "enabled": row.enabled_var.get(),
                "kind": row.kind,
                "interval_seconds": int(row_interval) if row_interval.isdigit() else None,
            })

        self.config["poll_interval_seconds"] = interval
        self.config["feeds"] = feeds
        self.config["lang"] = self.lang
        save_config(self.config)

        try:
            wants_autostart = self.autostart_var.get()
            currently_enabled = autostart_manager.is_enabled()
            if wants_autostart and not currently_enabled:
                autostart_manager.enable()
            elif not wants_autostart and currently_enabled:
                autostart_manager.disable()
        except Exception as exc:
            messagebox.showerror(self.t("autostart_error_title"), self.t("autostart_error_msg", error=exc))
            return

        messagebox.showinfo(self.t("ok_title"), self.t("ok_msg"))


def main() -> None:
    config = load_config()
    root = tk.Tk()
    SettingsApp(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
