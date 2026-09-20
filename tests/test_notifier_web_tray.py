"""Tests de la migration Qt -> web+pystray : SharedState (remplace les
signaux Qt), build_feeds_from_rows (remplace SettingsWindow.on_save), les
routes HTTP reelles (build_api_routes + _serve_web, sur un port ephemere
et un DATA_DIR temporaire - jamais les vraies donnees), et la construction
du tray (jamais icon.run(), voir la lecon de la migration lidar2map).

Piege connu (voir memoire feedback-migrer-donnees-installdir-piege-test) :
data_paths.migrer_donnees_existantes() lit INSTALL_DIR, jamais patchable,
qui pointe toujours vers le vrai dossier du projet. Aucun test ici
n'appelle notifier.main() ni migrer_donnees_existantes() : build_api_routes
et _construire_tray suffisent a exercer le vrai code sans passer par elles.
"""
import builtins
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import notifier


class SharedStateTests(unittest.TestCase):
    def setUp(self):
        self.state = notifier.SharedState(threading.Event())

    def test_no_info_resets_to_none_when_not_inflight(self):
        self.state.mark_update_seen({"version": "9.0.0"})
        self.state.mark_update_seen(None)
        snap = self.state.update_snapshot()
        self.assertEqual(snap["status"], notifier.UPDATE_NONE)
        self.assertIsNone(snap["info"])

    def test_concurrent_empty_check_does_not_erase_inflight_download(self):
        self.state.mark_update_seen({"version": "9.0.0"})
        self.assertTrue(self.state.begin_update())
        # Un check concurrent revient vide pendant que begin_update() a deja
        # bascule en PREPARING : ne doit pas effacer update_info (meme garde
        # que l'ancien TrayApp._on_update_available).
        self.state.mark_update_seen(None)
        snap = self.state.update_snapshot()
        self.assertEqual(snap["status"], notifier.UPDATE_PREPARING)
        self.assertEqual(snap["info"]["version"], "9.0.0")

    def test_begin_update_refuses_double_start(self):
        self.state.mark_update_seen({"version": "1.2.3"})
        self.assertTrue(self.state.begin_update())
        self.assertFalse(self.state.begin_update())

    def test_begin_update_refuses_without_known_version(self):
        self.assertFalse(self.state.begin_update())

    def test_mark_failed_clears_inflight_and_records_error(self):
        self.state.mark_update_seen({"version": "1.2.3"})
        self.state.begin_update()
        self.state.mark_update_failed({"code": "download_failed", "detail": "x"})
        snap = self.state.update_snapshot()
        self.assertEqual(snap["status"], notifier.UPDATE_FAILED)
        self.assertEqual(snap["error"]["code"], "download_failed")
        self.assertFalse(self.state.begin_update() is False and self.state.update_inflight)

    def test_clear_inflight_allows_a_new_begin_update(self):
        self.state.mark_update_seen({"version": "1.2.3"})
        self.state.begin_update()
        self.state.clear_inflight()
        self.assertTrue(self.state.begin_update())


class BuildFeedsFromRowsTests(unittest.TestCase):
    def test_blank_row_is_skipped(self):
        feeds = notifier.build_feeds_from_rows([
            {"label": "", "url": "", "enabled": False, "kind": "rss"},
            {"label": "Kept", "url": "https://example.test/a", "enabled": True, "kind": "rss", "interval_seconds": 60},
        ])
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0]["label"], "Kept")

    def test_duplicate_labels_get_suffixed_keys(self):
        rows = [
            {"key": "", "label": "Same", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60},
            {"key": "", "label": "Same", "url": "https://b.test", "enabled": False, "kind": "rss", "interval_seconds": 60},
        ]
        feeds = notifier.build_feeds_from_rows(rows)
        self.assertEqual([f["key"] for f in feeds], ["same", "same_2"])

    def test_existing_key_is_reused_not_reslugified(self):
        # Le client renvoie la clef deja assignee (stashee cote JS comme
        # checkbox._feed_key l'etait en Qt) : un renommage du label ne doit
        # jamais regenerer une nouvelle clef, sous peine de perdre
        # l'historique de dedup (state/<key>.json) de cette source.
        rows = [{"key": "my_source", "label": "Renamed", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60}]
        feeds = notifier.build_feeds_from_rows(rows)
        self.assertEqual(feeds[0]["key"], "my_source")

    def test_missing_label_falls_back_to_key(self):
        feeds = notifier.build_feeds_from_rows([{"key": "", "label": "", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60}])
        self.assertEqual(feeds[0]["label"], "source")

    def test_invalid_interval_falls_back_to_kind_default(self):
        feeds = notifier.build_feeds_from_rows([
            {"key": "", "label": "X", "url": "https://a.test", "enabled": True, "kind": "github_issues", "interval_seconds": None},
        ])
        expected = getattr(notifier.PROVIDERS["github_issues"], "DEFAULT_INTERVAL_SECONDS", 60)
        self.assertEqual(feeds[0]["interval_seconds"], expected)

    def test_unknown_kind_falls_back_to_default_kind(self):
        feeds = notifier.build_feeds_from_rows([
            {"key": "", "label": "X", "url": "https://a.test", "enabled": True, "kind": "not_a_real_kind", "interval_seconds": 60},
        ])
        self.assertEqual(feeds[0]["kind"], notifier.DEFAULT_KIND)


class TrayDisponibleTests(unittest.TestCase):
    def test_generic_exception_at_import_is_treated_as_unavailable(self):
        # Regression lidar2map (pystray sur Linux sans X11) : l'import de
        # pystray peut lever Xlib.error.DisplayNameError, un RuntimeError,
        # pas un ImportError. except Exception, pas except ImportError.
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pystray":
                raise RuntimeError("no X11 display")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            self.assertFalse(notifier._tray_disponible())


class HttpApiTests(unittest.TestCase):
    """Sert les vraies routes (build_api_routes) sur un port ephemere
    (port=0, l'OS choisit un port libre : jamais de collision possible
    avec une vraie instance ou un autre test parallele) et un DATA_DIR
    temporaire. autostart_manager entierement mocke : ce test ne doit
    jamais toucher le vrai dossier de demarrage Windows/systemd/launchd."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name) / "data"
        self.data_dir.mkdir()
        self.data_dir_patch = mock.patch.object(notifier.data_paths, "DATA_DIR", self.data_dir)
        self.config_file_patch = mock.patch.object(notifier, "CONFIG_FILE", self.data_dir / "config.json")
        self.state_dir_patch = mock.patch.object(notifier, "STATE_DIR", self.data_dir / "state")
        self.history_file_patch = mock.patch.object(
            notifier.notification_history, "HISTORY_FILE", self.data_dir / "notification_history.json",
        )
        for patch in (self.data_dir_patch, self.config_file_patch, self.state_dir_patch, self.history_file_patch):
            patch.start()

        self.autostart_enabled = False

        def _enable():
            self.autostart_enabled = True

        def _disable():
            self.autostart_enabled = False

        self.autostart_patch = mock.patch.multiple(
            notifier.autostart_manager,
            is_enabled=lambda: self.autostart_enabled,
            enable=_enable,
            disable=_disable,
        )
        self.autostart_patch.start()

        notifier.save_config(notifier.default_config())

        self.pause_event = threading.Event()
        self.state = notifier.SharedState(self.pause_event)
        self.stop_event = threading.Event()
        api_routes, post_routes = notifier.build_api_routes(self.pause_event, self.state, self.stop_event)
        self.server = notifier._serve_web.demarrer(
            bind="127.0.0.1", port=0, trusted_host="", gui_dir=notifier.GUI_DIR,
            api_routes=api_routes, post_routes=post_routes,
        )
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.autostart_patch.stop()
        for patch in (self.history_file_patch, self.state_dir_patch, self.config_file_patch, self.data_dir_patch):
            patch.stop()
        self.tempdir.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, r.read()

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())

    def test_index_and_static_assets_are_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"watch2notif", body)
        self.assertEqual(self._get("/app.js")[0], 200)
        self.assertEqual(self._get("/style.css")[0], 200)

    def test_unknown_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/does-not-exist")
        self.assertEqual(ctx.exception.code, 404)

    def test_state_reflects_isolated_empty_config(self):
        status, body = self._get("/api/state")
        data = json.loads(body)
        self.assertEqual(data["config"]["feeds"], [])
        self.assertFalse(data["autostart_enabled"])
        self.assertFalse(data["paused"])
        self.assertEqual(data["update"]["status"], notifier.UPDATE_NONE)

    def test_save_config_persists_and_returns_generated_keys(self):
        status, result = self._post("/api/save-config", {
            "lang": "fr",
            "autostart_enabled": True,
            "feeds": [{"key": "", "label": "Feed A", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 45}],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["feeds"][0]["key"], "feed_a")
        self.assertTrue(self.autostart_enabled)  # mock, jamais le vrai systeme

        on_disk = json.loads(notifier.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["lang"], "fr")
        self.assertEqual(on_disk["feeds"][0]["url"], "https://a.test")

    def test_set_pause_toggles_the_real_event(self):
        self._post("/api/set-pause", {"paused": True})
        self.assertTrue(self.pause_event.is_set())
        status, body = self._get("/api/state")
        self.assertTrue(json.loads(body)["paused"])

        self._post("/api/set-pause", {"paused": False})
        self.assertFalse(self.pause_event.is_set())

    def test_update_install_without_available_update_is_rejected(self):
        status, result = self._post("/api/update-install", {})
        self.assertIn("error", result)

    def test_update_install_starts_worker_when_available(self):
        # Mocker _run_update_worker (la cible du thread), jamais
        # threading.Thread lui-meme : ce dernier est le MEME objet module
        # que celui utilise par _serve_web/ThreadingHTTPServer pour traiter
        # chaque requete HTTP - le patcher globalement bloque le serveur
        # en plein test (constate : timeout sur la reponse HTTP elle-meme).
        self.state.mark_update_seen({"version": "9.9.9", "page": "https://example.test"})
        with mock.patch.object(notifier, "_run_update_worker") as worker:
            status, result = self._post("/api/update-install", {})
            # Laisse le vrai thread demon demarrer et appeler le worker mocke.
            for _ in range(50):
                if worker.called:
                    break
                time.sleep(0.02)
        self.assertTrue(result["ok"])
        worker.assert_called_once()
        self.assertEqual(worker.call_args.args[1], "9.9.9")

    def test_history_empty_then_populated_after_a_real_notify_call(self):
        self.assertEqual(json.loads(self._get("/api/history")[1]), {"entries": []})
        with mock.patch.object(notifier.notify_backend, "notify"):
            notifier.notify("Some feed", {"title": "T", "author": "A", "summary": "", "link": "https://x.test"})
        entries = json.loads(self._get("/api/history")[1])["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["feed_label"], "Some feed")

        self._post("/api/clear-history", {})
        self.assertEqual(json.loads(self._get("/api/history")[1]), {"entries": []})


@unittest.skipUnless(notifier._tray_disponible(), "zone de notification indisponible sur cette machine")
class TrayMenuTests(unittest.TestCase):
    """Construit le vrai tray (pystray) et inspecte son menu, sans jamais
    appeler icon.run() - un test qui l'appellerait bloquerait indefiniment
    et ferait apparaitre une vraie icone (regression constatee pendant la
    migration lidar2map, cf. memoire de session)."""

    def setUp(self):
        self.pause_event = threading.Event()
        self.state = notifier.SharedState(self.pause_event)
        self.stop_event = threading.Event()
        self.lang_patch = mock.patch.object(notifier, "load_config", return_value={"lang": "en"})
        self.lang_patch.start()
        self.icon = notifier._construire_tray("http://127.0.0.1:0/", self.state, self.stop_event)

    def tearDown(self):
        self.stop_event.set()  # arrete le thread de rafraichissement du menu
        self.lang_patch.stop()

    def _labels(self):
        return [str(item) for item in self.icon.menu]

    def test_menu_has_no_update_item_when_none_available(self):
        labels = self._labels()
        self.assertEqual(len(labels), 5)
        self.assertTrue(any("pause" in label.lower() for label in labels))
        self.assertTrue(any(label == "Quit" for label in labels))

    def test_menu_shows_install_item_when_update_available(self):
        with mock.patch.object(notifier.self_update, "can_install_automatically", return_value=(True, "")):
            self.state.mark_update_seen({"version": "9.9.9"})
            labels = self._labels()
        self.assertEqual(len(labels), 6)
        self.assertTrue(any("9.9.9" in label for label in labels))

    def test_menu_shows_downloading_while_preparing(self):
        self.state.mark_update_seen({"version": "9.9.9"})
        self.state.begin_update()
        labels = self._labels()
        self.assertTrue(any("Downloading" in label for label in labels))

    def test_pause_toggle_flips_the_real_event(self):
        # MenuItem est appelable (__call__(icon) -> action(icon, item)) :
        # pas de toggle() public dans l'API pystray, c'est ainsi qu'un clic
        # reel invoque le callback.
        pause_item = next(item for item in self.icon.menu if "pause" in str(item).lower())
        self.assertFalse(self.pause_event.is_set())
        pause_item(self.icon)
        self.assertTrue(self.pause_event.is_set())


if __name__ == "__main__":
    unittest.main()
